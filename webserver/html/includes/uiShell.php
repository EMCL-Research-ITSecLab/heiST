<?php
declare(strict_types=1);
require_once __DIR__ . '/../vendor/autoload.php';

/** Serve the versioned React assets. API handlers remain the authorization boundary. */
function render_ui_shell(): void
{
    (new SecurityHelper())->initSecureSession();
    header('Cache-Control: no-store');
    $root = dirname(__DIR__);
    try {
        $manifest = json_decode(file_get_contents($root . '/ui-manifest.json'), true, flags: JSON_THROW_ON_ERROR);
        $assets = array_merge([$manifest['file']], $manifest['css'] ?? []);
        foreach ($assets as $asset) {
            if (!is_string($asset) || !preg_match('~^assets/ui/[a-zA-Z0-9_./-]+$~', $asset)
                || in_array('..', explode('/', $asset), true) || !is_file($root . '/' . $asset)) {
                throw new RuntimeException('UI asset is missing or invalid');
            }
        }
    } catch (Throwable $error) {
        error_log('heiST UI release assets unavailable: ' . get_class($error));
        http_response_code(503);
        echo '<!doctype html><html lang="en"><meta charset="utf-8"><title>heiST · Temporarily unavailable</title><main><h1>The interface is temporarily unavailable.</h1><p>Please contact your administrator.</p></main></html>';
        return;
    }
    $escape = static fn(string $value): string => htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    $route = basename(parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/');
    echo '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">';
    echo '<meta name="heist-page" content="' . $escape($route) . '"><meta name="theme-color" content="#142033"><title>heiST · Security training</title>';
    foreach ($manifest['css'] ?? [] as $css) {
        echo '<link rel="stylesheet" href="/' . $escape($css) . '">';
    }
    echo '</head><body><div id="root"></div><script type="module" src="/' . $escape($manifest['file']) . '"></script></body></html>';
}
