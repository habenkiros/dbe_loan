"""Shared collateral field-work constants."""

MIN_IMAGES_PER_BUILDING = 5
MIN_IMAGES_PER_LAND = 3
MIN_IMAGES_PER_OTHER_ITEM = 3

FIELD_VISIT_STEPS = (
    (1, 'Site & building'),
    (2, 'BOQ quantities'),
    (3, 'Photos'),
    (4, 'Review'),
)

LAND_FIELD_STEPS = (
    (1, 'Land & site'),
    (2, 'Photos'),
    (3, 'Review'),
)

OTHER_FIELD_STEPS = (
    (1, 'Asset details'),
    (2, 'Photos'),
    (3, 'Review'),
)

# Above this accuracy (metres), officer must attest GPS for audit / AI provenance.
GPS_ACCURACY_WEAK_THRESHOLD_M = 100

# Movable collateral: required photo types before submit (when policy enabled).
REQUIRED_MOVABLE_PHOTO_TYPES = (
    ('plate', 'Plate / registration'),
    ('asset', 'Full asset'),
    ('serial_label', 'Serial / chassis label'),
)

# Warn when EXIF embedded GPS differs from browser capture GPS by more than this (metres).
EXIF_GPS_MISMATCH_WARN_M = 200
