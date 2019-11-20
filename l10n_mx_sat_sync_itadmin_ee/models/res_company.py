# -*- coding: utf-8 -*-

from odoo import models, api, fields
from odoo.exceptions import Warning
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, DEFAULT_SERVER_DATE_FORMAT

import base64
import time
#import subprocess
#import tempfile
import logging

from datetime import datetime
from dateutil.relativedelta import relativedelta
from .portal_sat import PortalSAT

from lxml import etree

_logger = logging.getLogger(__name__)
from .special_dict import CaselessDictionary

TRY_COUNT = 3

from .esignature import convert_key_cer_to_pem


class ResCompany(models.Model):
    _inherit = 'res.company'

    last_cfdi_fetch_date = fields.Datetime("Última sincronización")
    l10n_mx_esignature_ids = fields.Many2many('l10n.mx.esignature.certificate', string='Certificado FIEL')
    
    @api.model
    def auto_import_cfdi_invoices(self):
#         for company in self.search([('l10n_mx_edi_fiel','!=',False),('l10n_mx_edi_fiel_key','!=',False)]):
        for company in self.search([('l10n_mx_esignature_ids','!=',False)]):
            company.download_cfdi_invoices()        
        return True
    
    @api.model
    def import_current_company_invoice(self):
        self.env.user.company_id.sudo().download_cfdi_invoices()
        return True
    
    @api.multi
    def download_cfdi_invoices(self, start_date=False, end_Date=False):
        esignature_ids = self.l10n_mx_esignature_ids
        esignature = esignature_ids.sudo().get_valid_certificate()
        if not esignature:
            raise Warning("Archivos incorrectos no son una FIEL.")
            
        if not esignature.content or not esignature.key or not esignature.password:
            raise Warning("Seleccine los archivos FIEL .cer o FIEL .pem.")

        fiel_cert_data = base64.b64decode(esignature.content)
        fiel_pem_data = convert_key_cer_to_pem(base64.decodestring(esignature.key), esignature.password.encode('UTF-8'))

        opt= {'credenciales':None,'rfc':None, 'uuid': None, 'ano': None, 'mes': None, 'dia': 0, 'intervalo_dias':None, 'fecha_inicial': None, 'fecha_final': None, 'tipo':'t', 'tipo_complemento':'-1', 'rfc_emisor': None, 'rfc_receptor': None, 'sin_descargar':False, 'base_datos': False, 'directorio_fiel' : '', 'archivo_uuids' : '', 'estatus':False}
        today = datetime.utcnow()
        if start_date and end_Date:
            opt['fecha_inicial'] = start_date
            opt['fecha_final'] = end_Date
        elif self.last_cfdi_fetch_date:
            last_import_date = self.last_cfdi_fetch_date #datetime.strptime(self.last_cfdi_fetch_date,DEFAULT_SERVER_DATETIME_FORMAT)
            last_import_date - relativedelta(days=2)
            
            fecha_inicial = last_import_date - relativedelta(days=2)
            fecha_final = today + relativedelta(days=2)
            opt['fecha_inicial'] = fecha_inicial
            opt['fecha_final'] = fecha_final
        else:
            ano = today.year
            mes = today.month    
            opt['ano']=ano
            opt['mes']=mes
        
        sat = False
        for i in range(TRY_COUNT):
            sat = PortalSAT(opt['rfc'], 'cfdi-descarga', False)
            if sat.login_fiel(fiel_cert_data, fiel_pem_data):
                time.sleep(1)
                break
        invoice_content_receptor, invoice_content_emisor = {}, {}
        if sat and sat.is_connect:
            invoice_content_receptor, invoice_content_emisor = sat.search(opt)
            sat.logout()
        elif sat:
            sat.logout()
        attachment_obj = self.env['ir.attachment']
        invoice_obj = self.env['account.invoice']
        
        #Supplier
        if invoice_content_receptor:
            uuids = list(invoice_content_receptor.keys())
            attachments = attachment_obj.sudo().search([('cfdi_uuid','in',uuids)])
            exist_uuids = attachments.mapped('cfdi_uuid')
            for uuid,data in invoice_content_receptor.items():
                if uuid in exist_uuids:
                    continue
                values = data[0]
                xml_content = data[1]
                #tree = etree.fromstring(xml_content)
                if b'xmlns:schemaLocation' in xml_content:
                    xml_content = xml_content.replace(b'xmlns:schemaLocation', b'xsi:schemaLocation')
                try:
                    tree = etree.fromstring(xml_content)
                except Exception as e:
                    _logger.error('error : '+str(e))
                    raise
                try:
                    ns = tree.nsmap
                    ns.update({'re': 'http://exslt.org/regular-expressions'})
                except Exception:
                    ns = {'re': 'http://exslt.org/regular-expressions'}
                    
                xml_content = base64.b64encode(xml_content)
                
                ns_url = ns.get('cfdi')
                root_tag = 'Comprobante'
                if ns_url:
                    root_tag = '{'+ns_url+'}Comprobante'
                #Validation to only admit CFDI
                if tree.tag != root_tag:
                    #Invalid invoice file.
                    continue
                
                #receptor_elements = tree.xpath('//cfdi:Emisor', namespaces=tree.nsmap)
                try:
                    receptor_elements = tree.xpath("//*[re:test(local-name(), 'Emisor','i')]", namespaces=ns)
                except Exception:
                    receptor_elements=False
                    _logger.info("No encontró al emisor")
                r_rfc, r_name, r_folio = '', '',''
                if receptor_elements:
                    attrib_dict = CaselessDictionary(dict(receptor_elements[0].attrib))
                    r_rfc = attrib_dict.get('rfc') #receptor_elements[0].get(attrib_dict.get('rfc'))
                    r_name = attrib_dict.get('nombre') #receptor_elements[0].get(attrib_dict.get('nombre'))
                r_folio = tree.get("Folio") #receptor_elements[0].get(attrib_dict.get('nombre'))

                cfdi_type = tree.get("TipoDeComprobante",'I')
                if cfdi_type not in ['I','E','P','N','T']:
                    cfdi_type = 'I'
                cfdi_type ='S'+cfdi_type
                
                filename = uuid + '.xml' #values.get('receptor','')[:10]+'_'+values.get('rfc_receptor')
                vals = dict(
                        name=filename,
                        datas_fname=filename,
                        type='binary',
                        datas=xml_content,
                        cfdi_uuid=uuid,
                        company_id=self.id,
                        cfdi_type=cfdi_type,
                        rfc_tercero = r_rfc,
                        nombre_tercero = r_name,
                        serie_folio = r_folio,
                        cfdi_total = values.get('total',0.0),
                    )
                if values.get('date_cfdi'):
                    vals.update({'date_cfdi' : values.get('date_cfdi').strftime(DEFAULT_SERVER_DATE_FORMAT)})
                invoice_exist = invoice_obj.search([('l10n_mx_edi_cfdi_uuid_cusom','=',uuid.lower()),('type','=','in_invoice')],limit=1)
                if not invoice_exist:
                    invoice_exist = invoice_obj.search([('l10n_mx_edi_cfdi_uuid_cusom','=',uuid.upper()),('type','=','in_invoice')],limit=1)
                if invoice_exist:
                    vals.update({'creado_en_odoo' : True,'invoice_ids':[(6,0, invoice_exist.ids)]})

                attachment_obj.create(vals)
        #Customer
        if invoice_content_emisor:
            uuids = list(invoice_content_emisor.keys())
            attachments = attachment_obj.sudo().search([('cfdi_uuid','in',uuids)])
            exist_uuids = attachments.mapped('cfdi_uuid')
            for uuid,data in invoice_content_emisor.items():
                if uuid in exist_uuids:
                    continue
                values = data[0]
                xml_content = data[1]
                #tree = etree.fromstring(xml_content)
                if b'xmlns:schemaLocation' in xml_content:
                    xml_content = xml_content.replace(b'xmlns:schemaLocation', b'xsi:schemaLocation')
                try:
                    tree = etree.fromstring(xml_content)
                except Exception as e:
                    _logger.error('error : '+str(e))
                    raise
                try:
                    ns = tree.nsmap
                    ns.update({'re': 'http://exslt.org/regular-expressions'})
                except Exception:
                    ns = {'re': 'http://exslt.org/regular-expressions'}
                xml_content = base64.b64encode(xml_content)
                
                ns_url = ns.get('cfdi')
                root_tag = 'Comprobante'
                if ns_url:
                    root_tag = '{'+ns_url+'}Comprobante'
                #Validation to only admit CFDI
                if tree.tag != root_tag:
                    #Invalid invoice file.
                    continue
                try:
                    emisor_elements = tree.xpath("//*[re:test(local-name(), 'Receptor','i')]", namespaces=ns)
                except Exception:
                    _logger.info("No encontró al receptor")
                e_rfc, e_name, r_folio = '', '', ''
                if emisor_elements:
                    attrib_dict = CaselessDictionary(dict(emisor_elements[0].attrib))
                    e_rfc = attrib_dict.get('rfc') #emisor_elements[0].get(attrib_dict.get('rfc'))
                    e_name = attrib_dict.get('nombre') #emisor_elements[0].get(attrib_dict.get('nombre'))
                r_folio = tree.get("Folio") #receptor_elements[0].get(attrib_dict.get('nombre'))

                cfdi_type = tree.get("TipoDeComprobante",'I')
                if cfdi_type not in ['I','E','P','N','T']:
                    cfdi_type = 'I'
                
                filename = uuid + '.xml' # values.get('emisor')[:10]+'_'+values.get('rfc_emisor')
                vals = dict(
                        name=filename,
                        datas_fname=filename,
                        type='binary',
                        datas=xml_content,
                        cfdi_uuid=uuid,
                        cfdi_type=cfdi_type,
                        company_id=self.id,
                        rfc_tercero = e_rfc,
                        nombre_tercero = e_name,
                        serie_folio = r_folio,
                        cfdi_total = values.get('total',0.0),
                    )
                if values.get('date_cfdi'):
                    vals.update({'date_cfdi' : values.get('date_cfdi').strftime(DEFAULT_SERVER_DATE_FORMAT)})
                invoice_exist = invoice_obj.search([('l10n_mx_edi_cfdi_uuid_cusom','=',uuid.lower()),('type','=','out_invoice')],limit=1)
                if not invoice_exist:
                    invoice_exist = invoice_obj.search([('l10n_mx_edi_cfdi_uuid_cusom','=',uuid.upper()),('type','=','out_invoice')],limit=1)
                if invoice_exist:
                    vals.update({'creado_en_odoo' : True,'invoice_ids':[(6,0, invoice_exist.ids)]})
                    
                attachment_obj.create(vals)
        self.write({'last_cfdi_fetch_date':today.strftime(DEFAULT_SERVER_DATETIME_FORMAT)})
        return
