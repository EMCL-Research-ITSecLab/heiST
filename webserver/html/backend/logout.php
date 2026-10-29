<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class LogoutHandler
{
    private ?int $userId;
    private string $csrfToken;
    private string $route;

    private ISecurityHelper $securityHelper;
    private ILogger $logger;

    private ISession $session;
    private IServer $server;
    private ICookie $cookie;
    
    private ISystem $system;

    /**
     * @throws Exception
     */
    public function __construct(
        ISecurityHelper $securityHelper = null,
        ILogger $logger = null,

        ISession $session = new Session(),
        IServer $server = new Server(),

        ISystem $system = new SystemWrapper(),
        ICookie $cookie = new Cookie()
    )
    {
        $this->session = $session;
        $this->server = $server;
        $this->cookie = $cookie;
        $this->route = "/logout";

        $this->securityHelper = $securityHelper ?? new SecurityHelper($logger, $session, $system);
        $this->logger = $logger ?? new Logger(route: $this->route, system: $system);
        
        $this->system = $system;

        $this->initSession();
        $this->validateSession();
        $this->parseRequest();
        $this->logger->logDebug("Initialized LogoutHandler for user ID: $this->userId");
    }

    private function initSession(): void
    {
        $this->securityHelper->initSecureSession();
    }

    /**
     * @throws Exception
     */
    private function validateSession(): void
    {
        if (!$this->securityHelper->validateSession() || empty($this->session['authenticated'])) {
            $this->logger->logWarning("Unauthorized logout attempt - IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown'));
            throw new CustomException('Unauthorized - Please login', 401);
        }

        $this->userId = $this->session['user_id'] ?? 'unknown';
    }

    private function parseRequest(): void
    {
        $this->csrfToken = $this->cookie['csrf_token'] ?? '';
    }

    public function handleRequest(): void
    {
        try {
            $this->validateCsrfToken();
            $this->destroySession();
            $this->sendSuccessResponse();
        } catch (CustomException $e) {
            $this->handleError($e);
        } // @codeCoverageIgnoreStart
        catch (Exception $e) {
            // most likely not reachable, gonna leave it here for safety
            $this->handleError(new Exception('Internal Server Error', 500));
        }
        // @codeCoverageIgnoreEnd
    }

    /**
     * @throws Exception
     */
    private function validateCsrfToken(): void
    {
        if (!$this->securityHelper->validateCsrfToken($this->csrfToken)) {
            $this->logger->logError("Invalid CSRF token during logout - User ID: $this->userId, Token: $this->csrfToken, IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown'));
            throw new CustomException('Invalid CSRF token', 403);
        }
    }

    private function destroySession(): void
    {
        $this->session->unset();
        $this->session->destroy();

        $this->expireSessionCookies();
    }

    private function expireSessionCookies(): void
    {
        $params = $this->session->get_cookie_params();
        $this->system->setcookie(
            $this->session->name(),
            '',
            [
                'expires' => $this->system->time() - 3600,
                'path' => $params['path'],
                'domain' => $params['domain'],
                'secure' => $params['secure'],
                'httponly' => $params['httponly'],
                'samesite' => $params['samesite'] ?? 'Strict'
            ]
        );

        $this->system->setcookie(
            'csrf_token',
            '',
            [
                'expires' => $this->system->time() - 3600,
                'path' => '/',
                'secure' => true,
                'httponly' => true,
                'samesite' => 'Strict'
            ]
        );
    }

    private function sendSuccessResponse(): void
    {
        echo json_encode([
            'success' => true,
            'message' => 'Logged out successfully'
        ]);
        defined('PHPUNIT_RUNNING') || exit;
    }

    private function handleError(Exception $e): void
    {
        $code = $e->getCode() ?: 500;
        http_response_code($code);

        $this->logger->logError("Logout failed - Code: $code, Message: " . $e->getMessage() .
            ", User ID: $this->userId" .
            ", IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown'));

        echo json_encode([
            'success' => false,
            'message' => $e->getMessage()
        ]);
        defined('PHPUNIT_RUNNING') || exit;
    }
}

// @codeCoverageIgnoreStart

if(defined('PHPUNIT_RUNNING'))
    return;

try {
    header('Content-Type: application/json');

    $handler = new LogoutHandler();
    $handler->handleRequest();
} catch (CustomException $e) {
    $errorCode = $e->getCode() ?: 500;
    http_response_code($errorCode);
    $logger = new Logger("/logout");
    $logger->logError("Error in logout endpoint: " . $e->getMessage() . " (Code: $errorCode)");
    $response = [
        'success' => false,
        'message' => $e->getMessage()
    ];

    if ($errorCode === 401) {
        $response['redirect'] = '/login';
    }

    echo json_encode($response);
} catch (Exception $e) {
    http_response_code(500);
    $logger = new Logger("/logout");
    $logger->logError("Unexpected error in logout endpoint: " . $e->getMessage());
    echo json_encode([
        'success' => false,
        'message' => 'An unexpected error occurred'
    ]);
}

// @codeCoverageIgnoreEnd