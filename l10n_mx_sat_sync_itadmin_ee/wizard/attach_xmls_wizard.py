

import base64

from lxml import etree, objectify

from odoo import _, api, fields, models
from odoo.exceptions import UserError

TYPE_CFDI22_TO_CFDI33 = {
    'ingreso': 'I',
    'egreso': 'E',
    'traslado': 'T',
    'nomina': 'N',
    'pago': 'P',
}


class AttachXmlsWizard(models.TransientModel):
    _name = 'multi.file.attach.xmls.wizard'
    
    dragndrop = fields.Char()

    @staticmethod
    def _xml2capitalize(xml):
        """Receive 1 lxml etree object and change all attrib to Capitalize.
        """
        def recursive_lxml(element):
            for attrib, value in element.attrib.items():
                new_attrib = "%s%s" % (attrib[0].upper(), attrib[1:])
                element.attrib.update({new_attrib: value})

            for child in element.getchildren():
                child = recursive_lxml(child)
            return element
        return recursive_lxml(xml)

    @staticmethod
    def _l10n_mx_edi_convert_cfdi32_to_cfdi33(xml):
        """Convert a xml from cfdi32 to cfdi33
        :param xml: The xml 32 in lxml.objectify object
        :return: A xml 33 in lxml.objectify object
        """
        if xml.get('version', None) != '3.2':
            return xml
        # TODO: Process negative taxes "Retenciones" node
        # TODO: Process payment term
        xml = AttachXmlsWizard._xml2capitalize(xml)
        xml.attrib.update({
            'TipoDeComprobante': TYPE_CFDI22_TO_CFDI33[
                xml.attrib['tipoDeComprobante']],
            'Version': '3.3',
            'MetodoPago': 'PPD',
        })
        return xml

    
    @api.model
    def l10n_mx_edi_get_tfd_etree(self, cfdi):
        '''Get the TimbreFiscalDigital node from the cfdi.

        :param cfdi: The cfdi as etree
        :return: the TimbreFiscalDigital node
        '''
        if not hasattr(cfdi, 'Complemento'):
            return None
        attribute = 'tfd:TimbreFiscalDigital[1]'
        namespace = {'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'}
        node = cfdi.Complemento.xpath(attribute, namespaces=namespace)
        return node[0] if node else None
    
    @api.model
    def check_xml(self, files):
        """ Validate that attributes in the xml before create invoice
        or attach xml in it
        :param files: dictionary of CFDIs in b64
        :type files: dict
        param account_id: The account by default that must be used in the
        lines of the invoice if this is created
        :type account_id: int
        :return: the Result of the CFDI validation
        :rtype: dict
        """
        if not isinstance(files, dict):
            raise UserError(_("Something went wrong. The parameter for XML "
                              "files must be a dictionary."))
        wrongfiles = {}
        attachments = {}
        attachment_uuids = {}
        attach_obj = self.env['ir.attachment']
        for key, xml64 in files.items():
            try:
                if isinstance(xml64, bytes):
                    xml64 = xml64.decode()
                xml_str = base64.b64decode(xml64.replace('data:text/xml;base64,', ''))
                # Fix the CFDIs emitted by the SAT
                xml_str = xml_str.replace(b'xmlns:schemaLocation', b'xsi:schemaLocation')
                xml = objectify.fromstring(xml_str)
            except (AttributeError, SyntaxError) as exce:
                wrongfiles.update({key: {
                    'xml64': xml64, 'where': 'CheckXML',
                    'error': [exce.__class__.__name__, str(exce)]}})
                continue
            xml = self._l10n_mx_edi_convert_cfdi32_to_cfdi33(xml)
            xml_tfd = self.l10n_mx_edi_get_tfd_etree(xml)
            
            xml_uuid = False if xml_tfd is None else xml_tfd.get('UUID', '')
            
            if not xml_uuid:
                msg = {'signed': True, 'xml64': True}
                wrongfiles.update({key: msg})
                continue
                
            cfdi_type = xml.get('TipoDeComprobante', 'I')
            attachment_uuids.update({xml_uuid : [xml64.replace('data:text/xml;base64,', ''), cfdi_type, key]})
            #uuids.append(xml_uuid)
            
        
        attas = attach_obj.sudo().search([('cfdi_uuid','in',list(attachment_uuids.keys()))])
        exist_uuids = attas.mapped('cfdi_uuid')
        company_id = self.env.user.company_id.id
        for uuid, data in attachment_uuids.items():
            if uuid in exist_uuids:
                continue
            xml64 = data[0]
            cfdi_type = data[1]
            key = data[2]
            #cfdi_type ='S'+cfdi_type
            
            filename = uuid + '.xml'
            attach_rec = attach_obj.with_context(is_fiel_attachment=True).create({'name' : filename,
                    'datas_fname' : filename,
                    'type' :'binary',
                    'datas' : xml64,
                    'company_id' :company_id,
                    'cfdi_type' : cfdi_type
                    })
            attachments.update({key: {'attachment_id': attach_rec.id}})
        
        return {'wrongfiles': wrongfiles,
                'attachments': attachments}

