-- Copyright (C) 2025 XXP
-- License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

-- neutralize cdek delivery credentials
UPDATE delivery_carrier
SET cdek_client_id = 'dummy',
    cdek_client_secret = 'dummy',
    cdek_access_token = 'dummy';
