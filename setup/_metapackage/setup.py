import setuptools

with open('VERSION.txt', 'r') as f:
    version = f.read().strip()

setuptools.setup(
    name="odoo-addons-xxp-odoo-erp-xxp-odoo-addons",
    description="Meta package for xxp-odoo-erp-xxp-odoo-addons Odoo addons",
    version=version,
    install_requires=[
        'odoo-addon-cdek_delivery>=16.0dev,<16.1dev',
        'odoo-addon-xxp_barcode_picking_shortcut>=16.0dev,<16.1dev',
    ],
    classifiers=[
        'Programming Language :: Python',
        'Framework :: Odoo',
        'Framework :: Odoo :: 16.0',
    ]
)
