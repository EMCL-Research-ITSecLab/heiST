<?php
declare(strict_types=1);
require_once __DIR__ . '/../vendor/autoload.php';

/** Browser bootstrap: user identity and CSRF only; infrastructure credentials stay server-side. */
final class UiSessionHandler
{
    private ISecurityHelper $security;
    private ISession $session;
    private IDatabaseHelper $database;

    public function __construct(
        ?ISecurityHelper $security = null,
        ISession $session = new Session(),
        ?IDatabaseHelper $database = null,
    ) {
        $this->session = $session;
        $this->security = $security ?? new SecurityHelper(session: $session);
        $this->database = $database ?? new DatabaseHelper();
    }

    public function response(): array
    {
        $this->security->initSecureSession();
        $token = $this->session['csrf_token'] ?? '';
        if (!is_string($token) || $token === '' || !$this->security->validateCsrfToken($token)) {
            $token = $this->security->generateCsrfToken();
        }
        $loggedIn = $this->security->validateSession(false, false);
        $user = null;
        $passwordChange = false;
        if ($loggedIn) {
            $pdo = $this->database->getPDO();
            $statement = $pdo->prepare('SELECT avatar_url, is_admin FROM get_header_data(:user_id)');
            $statement->execute(['user_id' => (int)$this->session['user_id']]);
            $record = $statement->fetch(PDO::FETCH_ASSOC);
            if (!$record) {
                throw new RuntimeException('Session account no longer exists');
            }
            $user = [
                'username' => (string)($this->session['username'] ?? ''),
                'avatar_url' => (string)($record['avatar_url'] ?? '/assets/avatars/default-avatar.png'),
                'is_admin' => filter_var($record['is_admin'], FILTER_VALIDATE_BOOLEAN),
            ];
            $passwordChange = $this->security->requiresPasswordChange();
        }
        return ['success' => true, 'data' => [
            'is_logged_in' => $loggedIn,
            'user' => $user,
            'requires_password_change' => $passwordChange,
            'csrf_token' => $token,
        ]];
    }
}

if (defined('PHPUNIT_RUNNING')) {
    return;
}
header('Content-Type: application/json');
header('Cache-Control: no-store, private');
header('Vary: Cookie');
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') {
    http_response_code(405);
    header('Allow: GET');
    echo json_encode(['success' => false, 'message' => 'Method not allowed']);
    return;
}
try {
    $result = (new UiSessionHandler())->response();
    setcookie('csrf_token', $result['data']['csrf_token'], [
        'expires' => time() + 3600, 'path' => '/', 'secure' => true,
        'httponly' => true, 'samesite' => 'Strict',
    ]);
    echo json_encode($result, JSON_THROW_ON_ERROR);
} catch (Throwable $error) {
    error_log('heiST session bootstrap failed: ' . get_class($error));
    http_response_code(503);
    echo json_encode(['success' => false, 'message' => 'Your session is temporarily unavailable. Please retry.']);
}
