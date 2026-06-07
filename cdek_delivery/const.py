# Copyright (C) 2025 XXP
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import re

from odoo import _

# CDEK API order types (``type`` field on order requests).
ORDER_TYPE = {
    "1": "E-Commerce",
    "2": "Delivery",
}

# Delivery endpoint types supported by CDEK tariffs and carriers.
DELIVERY_TYPE_FROM = [
    ("door", "Door"),
    ("office", "Office"),
    ("terminal", "Terminal"),
]

# Delivery methods available on partners; extends ``DELIVERY_TYPE_FROM`` with postbox.
DELIVERY_METHODS = [
    *DELIVERY_TYPE_FROM,
    ("postbox", "Postbox"),
]

# CDEK additional service codes mapped to human-readable labels.
# Keys are API ``code`` values; labels are translated at runtime via ``_()``.
CDEK_REFERENCE_SELECTION = {
    "INSURANCE": "Insurance",
    "TAKE_SENDER": "Pickup in Sender City",
    "DELIV_RECEIVER": "Delivery in Receiver City",
    "TRYING_ON": "Trying On",
    "PART_DELIV": "Partial Delivery",
    "DANGER_CARGO": "Dangerous Cargo",
    "SMS": "SMS Notification of Order Delivery",
    "THERMAL_MODE": "Thermal Mode",
    "NOTIFY_ORDER_CREATED": "Notification of Order Creation in CDEK",
    "NOTIFY_ORDER_DELIVERY": "Notification of Order Acceptance for Delivery",
    "BUBBLE_WRAP": "Bubble Wrap",
    "WASTE_PAPER": "Waste Paper",
    "CARTON_FILLER": "Pressed Cardboard Filler (55x14x2.3 cm)",
    "XL_BOX_INNER_CRATE": "Inner Crate Box XL",
    "20_KG_BOX_INNER_CRATE": "Inner Crate Box up to 20 kg",
    "30_KG_BOX_INNER_CRATE": "Inner Crate Box up to 30 kg",
    "BAN_ATTACHMENT_INSPECTION": "Ban Attachment Inspection",
    "GET_UP_FLOOR_BY_HAND": "Floor Delivery by Stairs",
    "GET_UP_FLOOR_BY_ELEVATOR": "Floor Delivery by Elevator",
    "ADULT_GOODS": "18+",
    "LOADING_OPERATIONS_AT_THE_SENDER": "Loading Operations at the Sender",
    "LOAD_THE_OPERATION_AT_THE_RECIPIENT": "Loading Operations at the Recipient",
    "ENVELOPE_A4_CDEK_FREE": "A4 Cardboard Envelope (Free)",
    "CUSTOMS_CLEARANCE": "Customs Clearance",
    "ANOTHER": "Other",
    "SMS_NOTIFICATIONS_FOR_THE_RECIPIENT": "SMS Notification of Order Arrival",
    "SMS_NOTIFICATIONS_FOR_EXPIRATION_DATE": "SMS Notification of Storage Expiration",
    "EXP_REGIST_WITH_DOC": "Export Customs Clearance (with Documents)",
    "EXP_REGIST_WITHOUT_DOC": "Export Customs Clearance (without Documents)",
    "EXP_REGIST": "Export Customs Clearance",
    "CUSTOM_CLEARENCE_FOR_LAST_MILE_B2B_200": "Customs Clearance for Last Mile B2B 200-",  # noqa: E501
    "CUSTOMS_CLEARANCE_FOR_THE_LAST_MILE": "Customs Clearance for Last Mile",
    "CUSTOM_CLEARENCE_FOR_LAST_MILE_B2B_200469": "Customs Clearance for Last Mile B2B 200+",  # noqa: E501
    "CUSTOM_CLEARENCE_FOR_B2B_1000_EXPORT": "Customs Clearance B2B 1000+ Export",
    "CUSTOM_CLEARENCE_FOR_B2B_200_IMPORT": "Customs Clearance B2B 200+ Import",
    "SELF_CLEARING_CUSTOMS_FOR_B2B_EXPORT": "Self-Clearing Customs B2B Export",
    "SELF_CLEARING_CUSTOMS_FOR_B2B_IMPORT": "Self-Clearing Customs B2B Import",
    "PHOTO_OF_DOCUMENTS": "Photo of Documents",
    "COURIER_PACKAGE_A2": "Courier Package A2",
    "PACKAGE_A_2_LIGHT_EXPRESS": "Courier Package Light A2 (White)",
    "PACKAGE_A_3_LIGHT_EXPRESS": "Courier Package Light A3 (White)",
    "PACKAGE_A_4_LIGHT_EXPRESS": "Courier Package Light A4 (White)",
    "PACKAGE_A_5_LIGHT_EXPRESS": "Courier Package Light A5 (White)",
    "CARTON_BOX_XS": "Box XS (0.5 kg 17x12x9 cm)",
    "CARTON_BOX_S_2_KILOS": "Box S (2 kg 23x19x10 cm)",
    "CARTON_BOX_M": "Box M (5 kg 33x25x15 cm)",
    "CARTON_BOX_2KG": "Box (2 kg 34x24x10 cm)",
    "CARTON_BOX_3KG": "Box (3 kg 24x24x21 cm)",
    "CARTON_BOX_5KG": "Box (5 kg 40x24x21 cm)",
    "CARTON_BOX_10KG": "Box (10 kg 40x35x28 cm)",
    "CARTON_BOX_L_12_KILOS": "Box (12 kg 31x25x38 cm)",
    "CARTON_BOX_XL_18_KILOS": "Box (18 kg 60x35x30 cm)",
    "CARTON_BOX_20KG": "Box (20 kg 47x40x43 cm)",
    "CARTON_BOX_30KG": "Box (30 kg 69x39x42 cm)",
}

# Input validation patterns for CDEK service parameters.
# Keys are tuples of service codes; values are ``(regex, error message)`` pairs.
CDEK_SERVICE_FORMAT = {
    (
        "COURIER_PACKAGE_A2",
        "PACKAGE_A_2_LIGHT_EXPRESS",
        "PACKAGE_A_3_LIGHT_EXPRESS",
        "PACKAGE_A_4_LIGHT_EXPRESS",
        "PACKAGE_A_5_LIGHT_EXPRESS",
        "CARTON_BOX_XS",
        "CARTON_BOX_S_2_KILOS",
        "CARTON_BOX_M",
        "CARTON_BOX_2KG",
        "CARTON_BOX_3KG",
        "CARTON_BOX_5KG",
        "CARTON_BOX_10KG",
        "CARTON_BOX_XL_18_KILOS",
        "CARTON_BOX_20KG",
        "CARTON_BOX_30KG",
        "CARTON_FILLER",
        "XL_BOX_INNER_CRATE",
        "20_KG_BOX_INNER_CRATE",
        "30_KG_BOX_INNER_CRATE",
    ): (re.compile("^[1-9]\\d*$"), _("Quantity must be an integer > 0")),
    ("INSURANCE",): (
        re.compile("^(0\\.\\d*[1-9]\\d*|[1-9]\\d*(\\.\\d+)?)$"),
        _("Price must be a positive"),
    ),
    ("BUBBLE_WRAP", "WASTE_PAPER"): (
        re.compile("^(0\\.\\d*[1-9]\\d*|[1-9]\\d*(\\.\\d+)?)$"),
        _("Length must be a positive"),
    ),
    ("SMS",): (
        re.compile("^[\\+]?[\\d\\s\\-\\(\\)\\.]{7,20}$"),
        _("Phone must be a valid phone number"),
    ),
}

# Maps CDEK service codes to the value type stored on sale order service lines.
CDEK_SERVICE_TYPE = {
    "counter": (
        "COURIER_PACKAGE_A2",
        "PACKAGE_A_2_LIGHT_EXPRESS",
        "PACKAGE_A_3_LIGHT_EXPRESS",
        "PACKAGE_A_4_LIGHT_EXPRESS",
        "PACKAGE_A_5_LIGHT_EXPRESS",
        "CARTON_BOX_XS",
        "CARTON_BOX_S_2_KILOS",
        "CARTON_BOX_M",
        "CARTON_BOX_2KG",
        "CARTON_BOX_3KG",
        "CARTON_BOX_5KG",
        "CARTON_BOX_10KG",
        "CARTON_BOX_XL_18_KILOS",
        "CARTON_BOX_20KG",
        "CARTON_BOX_30KG",
        "CARTON_FILLER",
        "XL_BOX_INNER_CRATE",
        "20_KG_BOX_INNER_CRATE",
        "30_KG_BOX_INNER_CRATE",
    ),
    "price": ("INSURANCE",),
    "length": ("BUBBLE_WRAP", "WASTE_PAPER"),
    "phone": ("SMS",),
}

# Odoo field names and validators for each CDEK service value type.
SERVICE_VALUE_FIELDS = {
    "counter": ("counter_value", lambda item: item and item > 0),
    "price": ("price_value", lambda item: item and item > 0),
    "length": ("length_value", lambda item: item and item > 0),
    "phone": ("phone_value", lambda item: item),
}

# Validation error messages keyed by CDEK service value type.
SERVICE_VALUE_ERRORS = {
    "counter": _("Counter value must be greater than 0"),
    "price": _("Price value must be greater than 0"),
    "length": _("Length value must be greater than 0"),
    "phone": _("Phone value must be a valid phone number"),
}

# Maps office search wizard types to ``res.partner.cdek_delivery_type`` values.
OFFICE_TYPES = {
    "ALL": "all",
    "PVZ": "office",
    "POSTAMAT": "postbox",
}
