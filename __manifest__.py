{
    'name': "AI Invoice OCR",
    'version': "18.0.0.1",
    'category': "Tools",
    'summary': """
        Scan an image and create a new Invoice Automatically | Odoo GPT | GPT Invoice | Chat GPT | Odoo OCR | AI Invoice OCR | AI Invoice Scan | AI Invoice Recognition | AI Invoice Reader 
        | AI Invoice Scanner | AI Invoice Scanning | AI Invoice Digitization | AI Invoice Digitize | AI Odoo Invoice OCR | AI Odoo Invoice Scan
        | AI Odoo OCR
    """,
    'author': "Javier Fernández",
    'website': "https://asdelmarketing.com",
    'license': 'OPL-1',
    'price': 47.99,
    'currency': 'EUR',
    'data': [
        'security/ir.model.access.csv',
        'views/ai_ocr_wizard.xml'
    ],
    'demo': [],
    'images': [
        'static/description/thumbnail.gif',
    ],
    'depends': [
        'web',
        'account',
        'hr',
        'hr_expense',
        'mail',
        'sale'
    ],
    "assets": {
    },
    'installable': True,
}