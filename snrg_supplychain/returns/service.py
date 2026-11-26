"""Compatibility imports; business transitions are now Frappe Workflow actions."""
from .native_service import *  # noqa: F401,F403


def transition(doc, action, reason=None):
    from .api import act
    return frappe.get_doc(act(doc.doctype, doc.name, action, reason))
