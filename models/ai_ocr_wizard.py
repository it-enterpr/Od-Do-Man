# -*- coding: utf-8 -*-

from odoo import models, fields, api
import logging
_logger = logging.getLogger(__name__)
from openai import OpenAI
from io import BytesIO
from PIL import Image
import base64
import io
import json
from pdf2image import convert_from_bytes
from odoo.exceptions import ValidationError


class AIOcrWizard(models.Model):
    _name = 'ai.ocr.wizard'
    _rec_name = 'file_name'
    _inherit = ['mail.thread.main.attachment', 'mail.activity.mixin']

    type = fields.Selection(selection=[('unknown', 'Unknown'), ('invoice', 'Invoice'), ('expense', 'Expense')], default="invoice", string="Type")
    file = fields.Binary(string="File", copy=False, attachment=True)
    file_name = fields.Char(string="File Name", compute="_compute_filename")
    state = fields.Selection(selection=[('draft', 'Draft'), ('done', 'Done'), ('error', 'Error')], string="Status", default='draft', copy=False)
    invoice_id = fields.Many2one(comodel_name='account.move', string="Invoice", copy=False)
    expense_id = fields.Many2one(comodel_name='hr.expense', string="Expense", copy=False)
    related_sale_order_id = fields.Many2one(comodel_name='sale.order', string="Related Sale Order", copy=False)
    related_project_task_id = fields.Many2one(comodel_name='project.task', string="Related Project Task", copy=False)
    amount = fields.Float(string="Amount", compute="_compute_amount", store=True)
    date = fields.Date(string="Date", compute="_compute_amount", store=True)
    errors = fields.Text(string="Errors", copy=False)
    user_id = fields.Many2one(comodel_name='res.users', string="User", default=lambda self: self.env.user)
    #purchase_order_id = fields.Many2one(comodel_name='purchase.order', string="Purchase Order")
    time_of_last_processing = fields.Datetime(string="Time of Last Processing", default=fields.Datetime.now)
    user_processed_id = fields.Many2one(comodel_name='res.users', string="User Processed", default=lambda self: self.env.user)
    
    @api.model
    def create(self, values):
        result = super(AIOcrWizard, self).create(values)
        result.set_main_attachment()
        result.rename_file_name()
        return result
    
    def write(self, values):
        result = super(AIOcrWizard, self).write(values)
        for record in self:
            if 'file' in values:
                record.set_main_attachment()
            if 'invoice_id' in values or 'expense_id' in values:
                record.rename_file_name()
        return result
    
    def _compute_filename(self):
        for record in self:
            number = record.invoice_id.name if record.invoice_id else record.expense_id.name if record.expense_id else ''
            record.file_name = f"{record.type}-{number if number else ''}-{record.date if record.date else ''}-{record.user_id.name if record.user_id else ''}"
    
    def set_main_attachment(self):
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'ai.ocr.wizard'),
            ('res_id', '=', self.id)
        ], limit=1)
        if not attachment and self.file:
            attachment = self.env['ir.attachment'].create({
                'name': self.file_name,
                'datas': self.file,
                'res_model': 'ai.ocr.wizard',
                'res_id': self.id,
                'type': 'binary'
            })
            
        if attachment:
            self._message_set_main_attachment_id(attachment, force=True)
            
    def rename_file_name(self):
        self.ensure_one()
        number = self.invoice_id.name if self.invoice_id else self.expense_id.name if self.expense_id else ''
        self.file_name = f"{self.type}-{number if number else ''}-{self.date if self.date else ''}-{self.user_id.name if self.user_id else ''}"
        
    @api.depends('invoice_id', 'expense_id')
    def _compute_amount(self):
        for record in self:
            try:
                if record.invoice_id:
                    record.amount = record.invoice_id.amount_total
                    record.date = record.invoice_id.invoice_date
                elif record.expense_id:
                    record.amount = record.expense_id.total_amount
                    record.date = record.expense_id.date
                else:
                    record.amount = 0
                    record.date = False
            except Exception as e:
                record.amount = 0
                record.date = False
                
    def action_process(self):
        # Process file to see if is an image or a pdf
        # If is an image, convert to base64
        # If is a pdf, convert to image and then to base64
        self.time_of_last_processing = fields.Datetime.now()
        self.user_processed_id = self.env.user
        if self.type == 'unknown':
            raise ValidationError('Select a type of document')
        file_name = self.file_name
        file = self.file
        # Calculate file size 
        file_size = len(file) * 3 / 4
        if file_size > 5000000:
            self.add_error('File size is too big. Max size is 5MB')
            self.state = 'error'
            self.env.cr.commit()
            return
        file_extension = file_name.split('.')[-1]
        try:
            if file_extension == 'pdf' or file_extension == 'PDF':
                image = self.convert_pdf_to_image(file)
                image = f"data:image/jpeg;base64,{image}"
                self.process_image(image)
            else:
                # if is an jpg image, convert to png
                if file_extension == 'jpg' or file_extension == 'jpeg' or file_extension == 'png':
                    im_bytes = base64.b64decode(file)   # im_bytes is a binary image
                    im_file = BytesIO(im_bytes)  # convert image to file-like object
                    img = Image.open(im_file)   # img is now PIL Image object
                    # convert to png
                    im_file = BytesIO()
                    img.save(im_file, format="png")
                    file = im_file.getvalue()

                # Convert to base64
                image_base64 = f"data:image/jpeg;base64,{base64.b64encode(file).decode('utf-8')}"
                # Process invoice
                self.process_image(image_base64)
                return True
        except Exception as e:
            _logger.info(e)
            self.add_error(e)
            self.state = 'error'
            self.env.cr.commit()
            return e
        
        #image_url = f"data:image/jpeg;base64,{self.encode_image(image_local)}"
        #self.process_image(image_url)
            

    def process_image(self, image):
        api_key = self.env['ir.config_parameter'].sudo().get_param('adm_ai_invoice_ocr.openai_api_key')
        if not api_key:
            self.add_error('OpenAI API Key not found in Odoo. Add key adm_ai_invoice_ocr.openai_api_key in System Parameters')
            self.state = 'error'
            self.env.cr.commit()
            return
        client = OpenAI(api_key=api_key)
        
        expense_products = self.env['product.product'].search([('can_be_expensed', '=', True)]).mapped(lambda r: r.name)
        
        prompt = "Return the data see in the image. Assume that the image is an supplier invoice"
        if self.type == 'expense':
            prompt = "Return the data see in the image. Assume that the image is an customer expense. For category use one of the following: " + ', '.join(expense_products)
        try:
            response = client.chat.completions.create(
                model='gpt-4o', 
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": image}
                            }
                        ],
                    }
                ],
                functions=[self.invoice_return_function() if self.type == 'invoice' else self.expense_return_function()],
                function_call={"name": "create_invoice" if self.type == 'invoice' else "create_expense"},
                max_tokens=2000,
            )

            # Extract JSON data from the response and remove Markdown formatting
            function_call = response.choices[0].message.function_call
            json_data = json.loads(function_call.arguments)
            
            if self.type == 'invoice':
                self.create_invoice(json_data)
            else:
                self.create_expense(json_data, image)
        except Exception as e:
            _logger.info(e)
            self.add_error('Error processing document in GPT-4 Vision API')
            self.state = 'error'
            self.env.cr.commit()
            return e
        _logger.info(json_data)

    def create_invoice(self, json_data):
        try:
            _logger.info(json_data)
            partner = self.get_partner(json_data)
            if json_data.get('invoice_date') == "":
                json_data['invoice_date'] = fields.Date.today()
            move_id = self.env['account.move'].create({
                'partner_id': partner,
                'invoice_date': json_data['invoice_date'],
                'move_type': 'in_invoice'
            })
            self.create_lines(move_id, json_data)
            _logger.info(move_id)
            self.write({
                'invoice_id': move_id.id,
                'state': 'done'
            })

        except Exception as e:
            _logger.info(e)
            self.add_error(e)
            self.state = 'error'
            self.env.cr.commit()
            return

    def create_expense(self, json_data, image):
        try:
            product = self.env['product.product'].search([('name', '=', json_data['category'])], limit=1)
            if not product:
                self.add_error(f"Product for category {json_data['category']} not found in Odoo")
                product = self.env['product.product'].create({
                    'name': json_data['category'],
                    'can_be_expensed': True
                })
                
            _logger.info(json_data)
            expense_id = self.env['hr.expense'].create({
                'name': json_data['description'],
                'product_id': product.id,
                'date': json_data['date'],
                'total_amount_currency': json_data['amount'],
            })
            
            self.write({
                'expense_id': expense_id.id,
                'state': 'done'
            })
            
            # Attach image to expense
            attachment = self.env['ir.attachment'].create({
                'name': self.file_name,
                'datas': self.file,
                'res_model': 'hr.expense',
                'res_id': expense_id.id,
                'type': 'binary'
            })
            self.expense_id._message_set_main_attachment_id(attachment, force=True)

        except Exception as e:
            _logger.info(e)
            self.add_error(e)
            self.state = 'error'
            self.env.cr.commit()
            return
        
    def create_lines(self, move_id, json_data):
        lines = []
        for line in json_data['invoice_lines']:
            created_line = self.env['account.move.line'].new()
            created_line['name'] = line['name']
            created_line['quantity'] = line['quantity']
            created_line['price_unit'] = line['unit_price']
            created_line['discount'] = line['discount']
            taxes = self.get_taxes(line['taxes'])
            product = self.get_product(line['name'])
            if not taxes or len(taxes) == 0:
                taxes = False
            created_line._compute_account_id()
            values = {
                'name': created_line['name'],
                'quantity': created_line['quantity'],
                'price_unit': created_line['price_unit'],
                'discount': created_line['discount'],
                'display_type': 'product'
            }
            if taxes:
                values['tax_ids'] = [(6, 0, taxes)]
            if product:
                values['product_id'] = product
            created_line = move_id.write({
                'invoice_line_ids': [(0, 0, values)]
            })

    def get_taxes(self, taxes):
        tax_ids = []
        for tax in taxes:
            tax_id = self.env['account.tax'].search([('name', '=', tax['name']), ('type_tax_use', '=', 'purchase'), ('company_id', '=', self.env.company.id)], limit=1)
            if not tax_id:
                self.add_error(f"Tax {tax['name']} not found in Odoo")
                continue
            tax_ids.append(tax_id.id)
        return tax_ids
    
    def get_product(self, display_name):
        product = self.env['product.product'].search([('name', '=', display_name)], limit=1)
        if not product and '[' in display_name:
            default_code = display_name.split(']')[0].replace('[', '').strip()
            product_name = display_name.split(']')[1].strip()
            product = self.env['product.product'].search([('default_code', '=', default_code)], limit=1)
            if not product:
                product = self.env['product.product'].search([('name', '=', product_name)], limit=1)
            
        if not product:
            product = self.env['product.product'].create({
                'name': display_name
            })
        return product.id

    def get_partner(self, json_data):
        partner = self.env['res.partner'].search([('vat', '=', json_data['partner']['vat']), ('parent_id', '=', False)], limit=1)
        if not partner:
            partner = self.env['res.partner'].search([('vat', '=', json_data['partner']['vat']), ('parent_id', '!=', False)], limit=1)
        if not partner:
            partner = self.env['res.partner'].search([('name', '=', json_data['partner']['name']), ('parent_id', '=', False)], limit=1)
        if not partner:
            partner = self.env['res.partner'].search([('name', '=', json_data['partner']['name']), ('parent_id', '!=', False)], limit=1)
        if not partner:
            vals = {
                'name': json_data['partner']['name'],
                'vat': json_data['partner']['vat']
            }
            try:
                partner = self.env['res.partner'].create(vals)
            except Exception as e:
                vals.pop('vat')
                partner = self.env['res.partner'].create(vals)
        return partner.id
            
    def get_state(self, state_name):
        state = self.env['res.country.state'].search([('name', '=', state_name)])
        if not state:
            self.add_error(f"State {state_name} not found in Odoo")
            return False
        return state.id
    
    def get_country(self, country_name):
        country = self.env['res.country'].search([('name', '=', country_name)])
        if not country:
            self.add_error(f"Country {country_name} not found in Odoo")
            return False
        return country.id


    def add_error(self, error):
        if self.errors:
            self.errors += f".\n{error}"
        else:
            self.errors = error
            
    def invoice_return_function(self):
        return {
            "name": "create_invoice",
            "description": "Creates an invoice with partner details and invoice lines",
            "parameters": {
                "type": "object",
                "required": [
                "partner",
                "invoice_date",
                "invoice_lines"
                ],
                "properties": {
                "partner": {
                    "type": "object",
                    "required": [
                    "name",
                    "vat",
                    ],
                    "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the partner or company. Unknow if not found"
                    },
                    "vat": {
                        "type": "string",
                        "description": "VAT number of the partner"
                    }
                    },
                    "additionalProperties": False
                },
                "invoice_date": {
                    "type": "string",
                    "description": "Date of the invoice in YYYY-MM-DD format. Empty if not found in the image"
                },
                "invoice_lines": {
                    "type": "array",
                    "description": "Line items included in the invoice",
                    "items": {
                    "type": "object",
                    "required": [
                        "name",
                        "quantity",
                        "unit_price",
                        "discount",
                        "taxes"
                    ],
                    "properties": {
                        "name": {
                        "type": "string",
                        "description": "Name of the item being invoiced"
                        },
                        "quantity": {
                        "type": "number",
                        "description": "Quantity of the item being invoiced"
                        },
                        "unit_price": {
                        "type": "number",
                        "description": "Price per unit of the item"
                        },
                        "discount": {
                        "type": "number",
                        "description": "Discount applied to the item"
                        },
                        "taxes": {
                        "type": "array",
                        "description": "List of taxes applied to the item",
                        "items": {
                            "type": "object",
                            "required": [
                            "name"
                            ],
                            "properties": {
                            "name": {
                                "type": "string",
                                "description": "Name of the tax"
                            }
                            },
                            "additionalProperties": False
                        }
                        }
                    },
                    "additionalProperties": False
                    }
                }
                },
                "additionalProperties": False
            }
        }
            
    def expense_return_function(self):
        return {
            "name": "create_expense",
            "description": "Creates an expense",
            "parameters": {
                "type": "object",
                "required": [
                "description",
                "category",
                "amount",
                "note"
                ],
                "properties": {
                "description": {
                    "type": "string",
                    "description": "A brief description of the expense"
                },
                "category": {
                    "type": "string",
                    "description": "The category to which the expense belongs"
                },
                "amount": {
                    "type": "number",
                    "description": "The total amount of the expense"
                },
                "date": {
                    "type": "string",
                    "description": "Date of the expense in YYYY-MM-DD format. Empty if not found in the image"
                },
                "note": {
                    "type": "string",
                    "description": "Additional notes regarding the expense"
                }
                },
                "additionalProperties": False
            }
        }

    def convert_pdf_to_image(self, pdf):
        # save in /tmp folder
        with open('/tmp/test.pdf', 'wb') as f:
            f.write(base64.b64decode(pdf))
        pdf_file_stream = io.BytesIO(pdf)
        pages = convert_from_bytes(base64.b64decode(pdf), dpi=200)
         # Guardar cada página como una imagen
        page = pages[0]
        with io.BytesIO() as image_buffer:
            # Guardar la imagen en el buffer
            page.save(image_buffer, format='JPEG')

            # Mover el cursor al inicio del buffer
            image_buffer.seek(0)

            # Leer los datos de la imagen y codificar en base64
            return base64.b64encode(image_buffer.getvalue()).decode('utf-8')