<?php
declare(strict_types=1);
require_once __DIR__ . '/../vendor/autoload.php';

/** Read-only diagnostics; authentication and administrator checks precede backend access. */
final class AdminOperationsHandler
{
    public function __construct(
        private ISecurityHelper $security,
        private IDatabaseHelper $database,
        private ICurlHelper $backend,
        private IAuthHelper $authentication,
    ) {}

    public function response(string $method): array
    {
        if ($method !== 'GET') {
            throw new CustomException('Method not allowed', 405);
        }
        $this->security->initSecureSession();
        if (!$this->security->validateSession()) {
            throw new CustomException('Please sign in', 401);
        }
        if (!$this->security->validateAdminAccess($this->database->getPDO())) {
            throw new CustomException('Administrator access required', 403);
        }
        $result = $this->backend->makeBackendRequest('/admin/operations', 'GET', $this->authentication->getBackendHeaders());
        if (!($result['success'] ?? false)) {
            throw new CustomException('Platform diagnostics are temporarily unavailable', 503);
        }
        $body = json_decode($result['response'] ?? '', true, flags: JSON_THROW_ON_ERROR);
        if (($body['success'] ?? false) !== true || !is_array($body['data'] ?? null)) {
            throw new CustomException('Platform diagnostics are temporarily unavailable', 503);
        }
        // The internal collector returns an explicit public contract, never its
        // settings, SSH output, authentication headers or raw transaction files.
        return ['success' => true, 'data' => array_intersect_key($body['data'], array_flip([
            'checked_at', 'database', 'maintenance', 'lifecycle', 'services', 'archive', 'release', 'source_version', 'storage'
        ]))];
    }
}

if (defined('PHPUNIT_RUNNING')) { return; }
header('Content-Type: application/json');
header('Cache-Control: no-store, private');
header('Vary: Cookie');
try {
    $env = new Env();
    $handler = new AdminOperationsHandler(new SecurityHelper(), new DatabaseHelper(), new CurlHelper($env), new AuthHelper(env: $env));
    echo json_encode($handler->response($_SERVER['REQUEST_METHOD'] ?? ''), JSON_THROW_ON_ERROR);
} catch (Throwable $error) {
    $status = (int)$error->getCode();
    if (!in_array($status, [401, 403, 405, 503], true)) { $status = 503; }
    http_response_code($status);
    if ($status === 405) { header('Allow: GET'); }
    echo json_encode(['success' => false, 'message' => match ($status) {
        401 => 'Please sign in', 403 => 'Administrator access required', 405 => 'Method not allowed',
        default => 'Platform diagnostics are temporarily unavailable. Please retry.'
    }]);
}
