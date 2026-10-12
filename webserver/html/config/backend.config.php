<?php

return [
    'filters' => [
        'ACTIVITY_TYPES' => ['all', 'solved', 'failed', 'active', 'badges'],
        'ACTIVITY_RANGES' => ['all', 'today', 'week', 'month', 'year'],
        'IMPORTANCE_LEVELS' => ['all', 'normal', 'important', 'critical'],
        'CHALLENGE_CATEGORIES' => ['all', 'web', 'crypto', 'forensics', 'reverse', 'pwn', 'misc'],
        'CHALLENGE_DIFFICULTIES' => ['all', 'easy', 'medium', 'hard'],
    ],
    'sorts' => [
        'VALID' => ['popularity', 'date', 'difficulty'],
    ],
    'badge' => [
        'REQUIRED_FIELDS' => ['id', 'name', 'description', 'icon', 'rarity', 'requirements'],
    ],
    'challenge' => [
        'ALLOWED_ACTIONS' => ['deploy', 'cancel', 'submit_flag', 'extend_time'],
        'MAX_TIME_EXTENSIONS' => 6,
        'EXTENSION_HOURS' => 1,
        'VALID_CATEGORIES' => ['web', 'crypto', 'forensics', 'reverse', 'pwn', 'misc'],
        'VALID_DIFFICULTIES' => ['easy', 'medium', 'hard'],
        'VALID_AD_ROLES' => ['none', 'dc', 'member'],
        'UPLOAD_DIR' => '/uploads/challenge_images/',
    ],
    'upload' => [
        'MAX_VIRTUAL_SIZE_BYTES' => 16 * 1024 ** 3,
        'MAX_SINGLE_VMDK_SIZE_BYTES' => 16 * 1024 ** 3,
        'MAX_TOTAL_VMDK_SIZE_BYTES' => 16 * 1024 ** 3,
        'MAX_VMDK_COUNT' => 8,
        'MAX_OVF_SIZE_BYTES' => 10 * 1024 ** 2,
        'UPLOAD_TEMP_DIR' => '/tmp/ova_uploads/',
    ],
    'announcement' => [
        'VALID_CATEGORIES' => ['general', 'updates', 'maintenance', 'events', 'security'],
        'IMPORTANCE_LEVELS' => ['normal', 'important', 'critical'],
    ],
    'dashboard' => [
        'VALID_DATA_TYPES' => [
            'user', 'progress', 'category', 'activity', 'badges',
            'active_challenge', 'challenges', 'timeline', 'news', 'all',
        ],
    ],
];