"""Generated neutral documents: no original certificate or personal data."""
from io import BytesIO

from pypdf import PdfWriter
from pypdf.constants import UserAccessPermissions
from pypdf.generic import DictionaryObject, NameObject, TextStringObject


def restricted_pdf(*, algorithm='AES-256', password='', active=False):
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=792, height=612)
    writer.add_metadata({'/Title': 'SYNTHETIC certificate compatibility fixture'})
    if active:
        writer._root_object[NameObject('/OpenAction')] = DictionaryObject({
            NameObject('/S'): NameObject('/JavaScript'),
            NameObject('/JS'): TextStringObject('/* synthetic; never executed */'),
        })
    writer.encrypt(user_password=password, owner_password='synthetic-owner-only',
                   permissions_flag=UserAccessPermissions.PRINT, algorithm=algorithm)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
