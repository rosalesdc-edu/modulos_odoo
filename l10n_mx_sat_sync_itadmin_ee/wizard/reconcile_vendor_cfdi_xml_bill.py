# -*- coding: utf-8 -*-
from odoo import models,fields,api
import base64
#from lxml import etree
import json, xmltodict
#from .cfdi_invoice import convert_to_special_dict

#from .special_dict import CaselessDictionary
from ...l10n_mx_sat_sync_itadmin_ee.models.special_dict import CaselessDictionary

import logging
_logger = logging.getLogger(__name__)

def convert_to_special_dict(d):
    for k, v in d.items():
        if isinstance(v, dict):
            d.__setitem__(k, convert_to_special_dict(CaselessDictionary(v)))
        else:
            d.__setitem__(k, v)
    return d

class ReconcileVendorCfdiXmlBill(models.TransientModel):
    _name ='reconcile.vendor.cfdi.xml.bill'
    
    typo_de_combante = fields.Selection([('I','Facturas de clientes'),('SI', 'Facturas de proveedor')], string='Tipo de Comprobante')
    
    @api.multi
    def action_reconcile(self):
        #selected_att_ids = self._context.get('select_ids',[])
        selected_att_ids = self._context.get('active_ids')
        
        if not selected_att_ids or self._context.get('active_model','')!='ir.attachment':
            return
        
        attachments = self.env['ir.attachment'].search([('id','in', selected_att_ids), ('creado_en_odoo','!=',True), ('cfdi_type','=', self.typo_de_combante)])
        
        invoice_obj = self.env['account.invoice']
        
        #cfdi_uuids = attachments.mapped("cfdi_uuid")
        #exist_invoices = invoice_obj.search([('l10n_mx_edi_cfdi_uuid','in',cfdi_uuids)])
        #exist_invoice_uuids = exist_invoices.mapped('l10n_mx_edi_cfdi_uuid')
        
        reconcile_obj = self.env['xml.invoice.reconcile']
        
        created_ids = []
        invoice_type = ''
        for attachment in attachments:
#             cfdi_uuid = attachment.cfdi_uuid
#             if not cfdi_uuid:
#                 continue
            
            file_content = base64.b64decode(attachment.datas)
            if b'xmlns:schemaLocation' in file_content:
                file_content = file_content.replace(b'xmlns:schemaLocation', b'xsi:schemaLocation')
            file_content = file_content.replace(b'cfdi:',b'')
            file_content = file_content.replace(b'tfd:',b'')
            try:
                data = json.dumps(xmltodict.parse(file_content)) #,force_list=('Concepto','Traslado',)
                data = json.loads(data)
            except Exception as e:
                data = {}
                raise Warning(str(e))
            
            data = CaselessDictionary(data)
            data = convert_to_special_dict(data)
            
            date_invoice = data.get('Comprobante',{}).get('@Fecha')
            total = data.get('Comprobante',{}).get('@Total')
#             try:
#                 tree = etree.fromstring(file_content)
#             except Exception as e:
#                 raise 
#             try:
#                 ns = tree.nsmap
#                 ns.update({'re': 'http://exslt.org/regular-expressions'})
#             except Exception:
#                 ns = {'re': 'http://exslt.org/regular-expressions'}
                
            if self.typo_de_combante=='I':
                element_tag = 'Receptor'
                invoice_type = 'out_invoice'
            else:
                element_tag = 'Emisor'
                invoice_type = 'in_invoice'
            cust_data = data.get('Comprobante',{}).get(element_tag,{})
            uso_data = data.get('Comprobante',{}).get('Receptor',{})
            client_rfc = cust_data.get('@rfc')
            client_name = cust_data.get('@nombre')
            
            timbrado_data = data.get('Comprobante',{}).get('Complemento',{}).get('TimbreFiscalDigital',{})
            
#             try:
#                 elements = tree.xpath("//*[re:test(local-name(), '%s','i')]"%(element_tag), namespaces=ns)
#             except Exception:
#                 _logger.info("No encontró al Emisor/Receptor")
#             client_rfc, client_name = '', ''
#             if elements:
#                 attrib_dict = CaselessDictionary(dict(elements[0].attrib))
#                 client_rfc = attrib_dict.get('rfc') 
#                 client_name = attrib_dict.get('nombre')

#             tree_attrib_dict = CaselessDictionary(dict(tree.attrib))
#             total = eval(tree_attrib_dict.get('total','0'))
            
            vals = {
                'client_name' : client_name,
                'date' : date_invoice, #tree_attrib_dict.get('fecha'),
                'amount' : total,
                'attachment_id' : attachment.id,

                'tipo_comprobante': data.get('Comprobante',{}).get('@TipoDeComprobante',{}),
                'folio_fiscal':timbrado_data.get('@UUID'),
                'forma_pago':data.get('Comprobante',{}).get('@FormaPago',{}),
                'methodo_pago':data.get('Comprobante',{}).get('@MetodoPago',{}),
                'uso_cfdi':uso_data.get('@UsoCFDI'),
                'numero_cetificado': timbrado_data.get('@NoCertificadoSAT'),
                'fecha_certificacion': timbrado_data.get('@FechaTimbrado'),
                'selo_digital_cdfi': timbrado_data.get('@SelloCFD'),
                'selo_sat': timbrado_data.get('@SelloSAT'),
                'tipocambio': data.get('Comprobante',{}).get('@TipoCambio'),
                }
            invoices = invoice_obj.search([('partner_id.vat','=',client_rfc),('amount_total','=',total),('type','=', invoice_type)])
            if invoices:
                inv = invoices.filtered(lambda x:x.state in ['open','draft'])
                if inv:
                    vals.update({'invoice_id':inv[0].id})
                else:
                    vals.update({'invoice_id':invoices[0].id})
            record = reconcile_obj.create(vals)
            created_ids.append(record.id)
        
        action = self.env.ref('l10n_mx_sat_sync_itadmin_ee.action_xml_invoice_reconcile_view').read()[0]
        action['domain'] = [('id', 'in', created_ids)]
        action['context'] = {'invoice_type': invoice_type}
        return action
    
    