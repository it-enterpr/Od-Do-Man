# -*- coding: utf-8 -*-
#License: Copyright Rolan Benavent Talens. All rights reserved.

from odoo import http
from odoo.http import request
import json
from io import BytesIO
from PIL import Image
import logging
_logger = logging.getLogger(__name__)

class LoginController(http.Controller):

    @http.route('/api/upload-to-ocr', type='json', auth="public", methods=['POST'], website=False)
    def api_login(self, **kw):
        """
            Controlador para manejar inicio de sesión y devolver aplicaciones activas.
        """
        try:
            if not kw.get('login') or not kw.get('password'):
                return {'error': 'Debe proporcionar login y password'}

            # Autenticar usuario
            uid = request.session.authenticate(request.env.cr.dbname, {'type': 'password', 'login': kw.get('login'), 'password': kw.get('password')})
            if not uid:
                return {'error': 'Credenciales incorrectas'}
            # Obtener datos del usuario autenticado
            user = request.env['res.users'].sudo().browse(uid.get('uid'))
            # use loged user
            wizard = request.env['ai.ocr.wizard'].create({
                'type': kw.get('type'),
                'file': kw.get('file'),
                'user_id': user.id,
                'file_name': kw.get('file_name'),
            })
            _logger.info(wizard)
            if kw.get('type') == 'unknown':
                return {
                    'state': 'done',
                    'message': 'Processed correctly'
                }
            try:
                wizard.action_process()
            except Exception as e:
                _logger.info(e)
                wizard.write({'state': 'error', 'errors': str(e)})
                
            if wizard.state == 'done':
                return {
                    'state': wizard.state,
                    'invoice': wizard.invoice_id.name,
                }
            elif wizard.state == 'error':
                return {
                    'state': wizard.state,
                    'error': wizard.errors,
                }
            else:
                return {
                    'state': wizard.state,
                }
        except Exception as e:
            _logger.info(e)
            return {
                'state': 'error',
                'a': 's',
                'error': str(e)
            }
