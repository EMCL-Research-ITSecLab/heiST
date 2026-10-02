<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class RegistrationHandler
{
    private PDO $pdo;
    private string $username;
    private string $email;
    private string $password;
    private string $confirmPassword;
    private string $csrfToken;
    private string $token;
    private bool $agreeTos;
    private array $generalConfig;
    private string $route;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;
    private IAuthHelper $authHelper;
    private ICurlHelper $curlHelper;

    private ISession $session;
    private IServer $server;
    private IPost $post;
    private ICookie $cookie;

    private ISystem $system;
    private IEnv $env;

    /**
     * @throws Exception
     */
    public function __construct(
        array $generalConfig,
        
        IDatabaseHelper $databaseHelper = null,
        ISecurityHelper $securityHelper = null,
        ILogger $logger = null,
        IAuthHelper $authHelper = null,
        ICurlHelper $curlHelper = null,
        
        ISession $session = new Session(),
        IServer $server = new Server(),
        IPost $post = new Post(),
        
        ISystem $system = new SystemWrapper(),
        IEnv $env = new Env(),
        ICookie $cookie = new Cookie()
    )
    {
        $this->session = $session;
        $this->server = $server;
        $this->post = $post;
        $this->cookie = $cookie;
        $this->env = $env;
        $this->route = "/signup";

        $this->databaseHelper = $databaseHelper ?? new DatabaseHelper($logger, $system);
        $this->securityHelper = $securityHelper ?? new SecurityHelper($logger, $session, $system);
        $this->logger = $logger ?? new Logger(route: $this->route, system: $system);
        $this->authHelper = $authHelper ?? new AuthHelper($logger, $system, $env);
        $this->curlHelper = $curlHelper ?? new CurlHelper($env);

        $this->system = $system;

        $this->generalConfig = $generalConfig;
        $this->initSession();
        $this->validateRequestMethod();
        $this->parseInput();
        $this->logger->logDebug("Initialized RegistrationHandler with Session ID: " . $this->session->id() ? hash('sha256', $this->session->id()) : 'no-session');
    }

    private function initSession(): void
    {
        $this->securityHelper->initSecureSession();
    }

    /**
     * @throws Exception
     */
    private function validateRequestMethod(): void
    {
        if ($this->server['REQUEST_METHOD'] !== 'POST') {
            throw new CustomException('Invalid request method', 405);
        }
    }

    private function parseInput(): void
    {
        $this->csrfToken = $this->post['csrf_token'] ?? '';
        $this->username = trim($this->post['username'] ?? '');
        $this->email = trim($this->post['email'] ?? '');
        $this->password = $this->post['password'] ?? '';
        $this->confirmPassword = $this->post['confirm-password'] ?? '';
        $this->token = trim($this->post['token'] ?? '');
        $this->agreeTos = isset($this->post['agree_tos']) &&
            ($this->post['agree_tos'] === 'on' || $this->post['agree_tos'] === '1' || $this->post['agree_tos'] === true);
    }

    public function handleRequest(): void
    {
        try {
            $this->validateInput();
            $this->validateCsrfToken();
            $this->validateToken();
            $this->checkCredentialsAvailability();
            $create_data = $this->createUserAccount();
            $userId = $create_data['user_id'];
            $vpnIp = $create_data['vpn_static_ip'];
            $this->updateLastLogin($userId);
            $this->initializeUserSession($userId);
            $this->sendSuccessResponse($userId, $vpnIp);
        } catch (CustomException $e) {
            $this->handleError($e);
        } catch (Exception $e) {
            $this->handleError(new Exception('Internal Server Error', 500));
        }
    }

    /**
     * @throws Exception
     */
    private function validateInput(): void
    {
        if (empty($this->username) || empty($this->email) || empty($this->password) || empty($this->confirmPassword) || empty($this->token)) {
            throw new CustomException('All fields are required', 400);
        }

        if (!$this->agreeTos) {
            $this->logger->logWarning("Registration attempt without ToS agreement - Username: $this->username, IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown'));
            throw new CustomException('You must agree to the Terms of Service and Privacy Policy', 400);
        }

        if (strlen($this->username) < $this->generalConfig['user']['MIN_USERNAME_LENGTH']) {
            throw new CustomException('Username must be at least' . $this->generalConfig['user']['MIN_USERNAME_LENGTH'] . 'characters long', 400);
        } elseif (strlen($this->username) > $this->generalConfig['user']['MAX_USERNAME_LENGTH']) {
            throw new CustomException('Username must not exceed ' . $this->generalConfig['user']['MAX_USERNAME_LENGTH'] . 'characters', 400);
        } elseif (!preg_match('/' . $this->generalConfig['user']['USERNAME_REGEX'] . '/', $this->username)) {
            throw new CustomException("Username contains invalid characters only '_' is allowed", 400);
        }

        if (strlen($this->email) > $this->generalConfig['user']['MAX_EMAIL_LENGTH']) {
            throw new CustomException('Email must not exceed ' . $this->generalConfig['user']['MAX_EMAIL_LENGTH'] . 'characters', 400);
        } elseif (!filter_var($this->email, FILTER_VALIDATE_EMAIL)) {
            throw new CustomException('Invalid email format', 400);
        }

        if (strlen($this->password) < $this->generalConfig['user']['MIN_PASSWORD_LENGTH']) {
            throw new CustomException('Password must be at least ' . $this->generalConfig['user']['MIN_PASSWORD_LENGTH'] . 'characters long', 400);
        } elseif (strlen($this->password) > $this->generalConfig['user']['MAX_PASSWORD_LENGTH']) {
            throw new CustomException('Password must not exceed ' . $this->generalConfig['user']['MAX_PASSWORD_LENGTH'] . 'characters', 400);
        }

        if ($this->password !== $this->confirmPassword) {
            throw new CustomException('Passwords do not match', 400);
        }
    }

    /**
     * @throws Exception
     */
    private function validateToken(): void
    {
        $lectureSignupToken = $this->env['LECTURE_SIGNUP_TOKEN'] ?? '';

        if (empty($lectureSignupToken)) {
            $this->logger->logError("LECTURE_SIGNUP_TOKEN environment variable is not set");
            throw new CustomException('Registration is currently unavailable', 500);
        }

        if ($this->token !== $lectureSignupToken) {
            $this->logger->logWarning("Invalid token provided for registration attempt. Username: " . $this->username . ", IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown'));
            throw new CustomException('Invalid token', 400);
        }

        $this->logger->logDebug("Token validation successful for username: " . $this->username);
    }

    /**
     * @throws Exception
     */
    private function validateCsrfToken(): void
    {
        if (!$this->securityHelper->validateCsrfToken($this->csrfToken)) {
            $this->logger->logError("CSRF token validation failed from IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown') ." with csrf_token=$this->csrfToken");
            throw new CustomException('Invalid CSRF token', 403);
        }
    }

    /**
     * @throws Exception
     */
    private function checkCredentialsAvailability(): void
    {
        $this->pdo = $this->databaseHelper->getPDO();

        $stmt = $this->pdo->prepare("SELECT is_username_taken(:username)");
        $stmt->execute(['username' => $this->username]);
        if ($stmt->fetch(PDO::FETCH_COLUMN) == 1) {
            $this->logger->logWarning("Registration attempt with existing username: $this->username");
            throw new CustomException('Username already taken', 400);
        }

        $stmt = $this->pdo->prepare("SELECT is_email_taken(:email)");
        $stmt->execute(['email' => $this->email]);
        if ($stmt->fetch(PDO::FETCH_COLUMN) == 1) {
            $this->logger->logWarning("Registration attempt with existing email: $this->email");
            throw new CustomException('Email already registered', 400);
        }
    }

    /**
     * @throws Exception
     */
    private function createUserAccount()
    {
        $passwordSalt = bin2hex(random_bytes(16));
        $passwordHash = hash('sha512', $passwordSalt . $this->password);
        if (!$passwordHash) {
            // @codeCoverageIgnoreStart
            // This should never happen unless the server is misconfigured
            throw new CustomException('Account creation failed', 500);
            // @codeCoverageIgnoreEnd
        }

        $this->pdo->beginTransaction();
        $ip_addr = $_SERVER['REMOTE_ADDR'];

        try {
            $stmt = $this->pdo->prepare("SELECT id AS user_id, vpn_static_ip FROM create_user(:username, :email, :password_hash, :password_salt, :ip_addr)");
            $stmt->execute([
                'username' => $this->username,
                'email' => $this->email,
                'password_hash' => $passwordHash,
                'password_salt' => $passwordSalt,
                'ip_addr' => $ip_addr
            ]);
            $result = $stmt->fetch(PDO::FETCH_ASSOC);

            if (!$result || empty($result['user_id']) || empty($result['vpn_static_ip'])) {
                throw new CustomException('Account creation failed', 500);
            }

            $this->logger->logInfo("User account created successfully - User ID: {$result['user_id']}, Username: $this->username");

            return $result;
        } catch (CustomException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database transaction failed: " . $e->getMessage());
            throw new CustomException('Account creation failed', 500);
        } catch (PDOException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Database error during account creation: " . $e->getMessage());
            throw new CustomException('Account creation failed', 500);
        } catch (Exception $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Unexpected error during account creation: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        } finally {
            if ($this->pdo->inTransaction()) {
                $this->pdo->commit();
            }
        }
    }

    private function updateLastLogin(int $userId): void
    {
        $update = $this->pdo->prepare("SELECT update_last_login(:id)");
        $update->execute(['id' => $userId]);
    }

    private function initializeUserSession($userId): void
    {
        $this->session->regenerate_id(true);
        $this->session['user_id'] = $userId;
        $this->session['ip'] = $this->server['REMOTE_ADDR'];
        $this->session['user_agent'] = $this->server['HTTP_USER_AGENT'];
        $this->session['last_activity'] = $this->system->time();
        $this->session['authenticated'] = true;
        $this->session['username'] = $this->username;

        $newCsrf = $this->securityHelper->generateCsrfToken();
        $this->system->setcookie(
            'csrf_token',
            $newCsrf,
            [
                'expires' => $this->system->time() + 3600,
                'path' => '/',
                'secure' => true,
                'httponly' => true,
                'samesite' => 'Strict'
            ]
        );

        $this->logger->logInfo("Successful registration for user $userId");
    }

    private function sendSuccessResponse($userId, $vpnIp): void
    {
        echo json_encode([
            'success' => true,
            'message' => 'Registration successful',
            'user_id' => $userId,
            'vpn_ip' => $vpnIp
        ]);
        defined('PHPUNIT_RUNNING') || exit;
    }

    private function handleError(Exception $e): void
    {
        $code = $e->getCode() >= 400 && $e->getCode() < 600 ? $e->getCode() : 400;
        http_response_code($code);

        $this->logger->logError("Registration error: " . $e->getMessage() . " [Code: $code]");

        echo json_encode([
            'success' => false,
            'message' => $e->getMessage(),
            'error_code' => $code
        ]);
        defined('PHPUNIT_RUNNING') || exit;
    }
}

// @codeCoverageIgnoreStart

if(defined('PHPUNIT_RUNNING'))
    return;

try {
    header('Content-Type: application/json');
    $system = new SystemWrapper();
    $generalConfig = json_decode($system->file_get_contents(__DIR__ . '/../config/general.config.json'), true);

    $handler = new RegistrationHandler(generalConfig: $generalConfig);
    $handler->handleRequest();
} catch (CustomException $e) {
    $errorCode = $e->getCode() ?: 500;
    http_response_code($errorCode);
    $logger = new Logger("/signup");
    $logger->logError("Error in signup endpoint: " . $e->getMessage() . " (Code: $errorCode)");
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
    $logger = new Logger("/signup");
    $logger->logError("Unexpected error in signup endpoint: " . $e->getMessage());
    echo json_encode([
        'success' => false,
        'message' => 'An unexpected error occurred'
    ]);
}

// @codeCoverageIgnoreEnd