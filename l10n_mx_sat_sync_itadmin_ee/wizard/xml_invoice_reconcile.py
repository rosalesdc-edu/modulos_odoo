# -*- coding: utf-8 -*-
from odoo import models,fields, api, _
from odoo.exceptions import Warning
import base64

import logging
_logger = logging.getLogger(__name__)

class XMLInvoiceReconcile(models.TransientModel):
    _name ='xml.invoice.reconcile'
    
    attachment_id = fields.Many2one('ir.attachment',"Xml Attachment")
    invoice_id = fields.Many2one('account.invoice',"Invoice")
    date = fields.Date("Date")
    #partner_id = fields.Many2one("res.partner","Client")
    client_name = fields.Char("Client")
    amount = fields.Float("Amount")
    reconcilled = fields.Boolean("Is Reconcilled ?")
    
    folio_fiscal = fields.Char("Folio Fiscal")
    forma_pago = fields.Selection(
        selection=[('01', '01 - Efectivo'), 
                   ('02', '02 - Cheque nominativo'), 
                   ('03', '03 - Transferencia electrónica de fondos'),
                   ('04', '04 - Tarjeta de Crédito'), 
                   ('05', '05 - Monedero electrónico'),
                   ('06', '06 - Dinero electrónico'), 
                   ('08', '08 - Vales de despensa'), 
                   ('12', '12 - Dación en pago'), 
                   ('13', '13 - Pago por subrogación'), 
                   ('14', '14 - Pago por consignación'), 
                   ('15', '15 - Condonación'), 
                   ('17', '17 - Compensación'), 
                   ('23', '23 - Novación'), 
                   ('24', '24 - Confusión'), 
                   ('25', '25 - Remisión de deuda'), 
                   ('26', '26 - Prescripción o caducidad'), 
                   ('27', '27 - A satisfacción del acreedor'), 
                   ('28', '28 - Tarjeta de débito'), 
                   ('29', '29 - Tarjeta de servicios'), 
                   ('30', '30 - Aplicación de anticipos'), 
                   ('99', '99 - Por definir'),],
        string=_('Forma de pago'),
    )
    uso_cfdi = fields.Selection(
        selection=[('G01', _('Adquisición de mercancías')),
                   ('G02', _('Devoluciones, descuentos o bonificaciones')),
                   ('G03', _('Gastos en general')),
                   ('I01', _('Construcciones')),
                   ('I02', _('Mobiliario y equipo de oficina por inversiones')),
                   ('I03', _('Equipo de transporte')),
                   ('I04', _('Equipo de cómputo y accesorios')),
                   ('I05', _('Dados, troqueles, moldes, matrices y herramental')),
                   ('I06', _('Comunicacion telefónica')),
                   ('I07', _('Comunicación Satelital')),
                   ('I08', _('Otra maquinaria y equipo')),
                   ('D01', _('Honorarios médicos, dentales y gastos hospitalarios')),
                   ('D02', _('Gastos médicos por incapacidad o discapacidad')),
                   ('D03', _('Gastos funerales')),
                   ('D04', _('Donativos')),
                   ('D07', _('Primas por seguros de gastos médicos')),
                   ('D08', _('Gastos de transportación escolar obligatoria')),
                   ('D10', _('Pagos por servicios educativos (colegiaturas)')),
                   ('P01', _('Por definir')),],
        string=_('Uso CFDI (cliente)'),
    )
    
    numero_cetificado = fields.Char("Numero cetificado")
    fecha_certificacion = fields.Char("Fecha certificacion")
    selo_digital_cdfi = fields.Char("Selo digital cdfi")
    selo_sat = fields.Char("Selo sat")
    tipocambio = fields.Char("Tipo cambio")
    tipo_comprobante = fields.Selection(
        selection=[('I', 'Ingreso'), 
                   ('E', 'Egreso'),
                    ('T', 'Traslado'),],
        string=_('Tipo de comprobante'),
    )

    @api.multi
    def action_reconcile(self):
        self.ensure_one()
        invoice = self.invoice_id
        if not invoice:
            raise Warning("Please select invoice first that you want to reconcile with XML file.")
        if invoice:
            invoice.write({'l10n_mx_edi_cfdi_uuid': self.folio_fiscal,
                           #'forma_pago' : self.forma_pago,
                           'l10n_mx_edi_usage' : self.uso_cfdi,
                           'l10n_mx_edi_cfdi_name' : self.attachment_id.datas_fname,
                           #'l10n_mx_edi_cfdi_certificate_id' : self.numero_cetificado,
                           #'fecha_certificacion' : self.fecha_certificacion,
                           #'selo_digital_cdfi' : self.selo_digital_cdfi,
                           #'selo_sat' : self.selo_sat,
                           #'tipocambio' : self.tipocambio,
                           #'tipo_comprobante': self.tipo_comprobante,
                           #'estado_factura': 'factura_correcta',
                           })
            self.attachment_id.write({'creado_en_odoo':True, 'invoice_ids':[(6,0, [invoice.id])], 'res_id': invoice.id, 'res_model': invoice._name,})
            _logger.info("Factura reconciliada")
            self.write({'reconcilled':True})
        return