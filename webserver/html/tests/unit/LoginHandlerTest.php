<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\TestCase;

class LoginHandlerTest extends TestCase
{
    private PDO $pdo;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;

    private ISession $session;
    private IServer $server;
    private IPost $post;

    private ISystem $system;

    protected function setUp(): void
    {
        // Mock dependencies
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->logger = new MockLogger();

        $this->session = new MockSession();
        $this->server = new MockServer();
        $this->post = new MockPost();

        $this->system = $this->createStub(ISystem::class);
    }

    public function testAlreadyAuthenticatedWithoutCsrfTokenRedirectsCorrectly(): void
    {
        $this->session = new MockSession();
        $this->securityHelper = new SecurityHelper($this->logger, $this->session, new MockSystem());

        $this->server['REQUEST_METHOD'] = 'GET';
        $this->server['REMOTE_ADDR'] = '10.0.0.200';

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['csrf_token'] = null;
        $this->session['authenticated'] = true;

        $this->system = new MockSystem();

        $this->assertEmpty($this->system->getCookies());

        ob_start();
        $loginHandler = new LoginHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->post,
            $this->system
        );
        $output = ob_get_clean();
        $jsonOutput = json_decode($output, true);

        $this->assertTrue($jsonOutput['success']);
        $this->assertNotNull($jsonOutput['csrf_token']);
        $this->assertEquals('/dashboard', $jsonOutput['redirect']);
    }

    public function testEmptyCsrfTokenOnPostRequestReturnsError(): void
    {
        $this->session = new MockSession();
        $this->securityHelper = new SecurityHelper($this->logger, $this->session, new MockSystem());

        $this->server['REQUEST_METHOD'] = 'POST';
        $this->server['REMOTE_ADDR'] = '10.0.0.200';
        $this->post['csrf_token'] = null;
        $this->post['username'] = 'admin';
        $this->post['password'] = 'password';

        $this->system = new MockSystem();

        ob_start();
        $handler = new LoginHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->post,
            $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $jsonOutput = json_decode($output, true);

        $this->assertFalse($jsonOutput['success']);
        $this->assertStringContainsString("Invalid request token", $jsonOutput['message']);
    }

    public function testInvalidCsrfTokenFormatOnPostRequestReturnsError(): void
    {
        $this->session = new MockSession();
        $this->securityHelper = $this->createStub(SecurityHelper::class);
        $this->securityHelper->method('validateCsrfToken')
            ->willReturn(false);

        $this->server['REQUEST_METHOD'] = 'POST';
        $this->server['REMOTE_ADDR'] = '10.0.0.200';
        $this->post['csrf_token'] = 'invalid_token';

        ob_start();
        $handler = new LoginHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->post,
            $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $jsonOutput = json_decode($output, true);

        $this->assertFalse($jsonOutput['success']);
        $this->assertStringContainsString("Invalid CSRF token", $jsonOutput['message']);
    }

    public function testEmptyUsernameOnPostRequestReturnsError(): void
    {
        $this->session = new MockSession();
        $this->securityHelper = $this->createStub(SecurityHelper::class);
        $this->securityHelper->method('validateCsrfToken')
            ->willReturn(true);

        $this->server['REQUEST_METHOD'] = 'POST';
        $this->server['REMOTE_ADDR'] = '10.0.0.200';
        $this->post['csrf_token'] = 'valid_token';
        $this->post['username'] = '';
        $this->post['password'] = 'password';

        ob_start();
        $handler = new LoginHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->post,
            $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $jsonOutput = json_decode($output, true);

        $this->assertFalse($jsonOutput['success']);
        $this->assertStringContainsString("Username is required", $jsonOutput['message']);
    }

    public function testEmptyPasswordOnPostRequestReturnsError(): void
    {
        $this->session = new MockSession();
        $this->securityHelper = $this->createStub(SecurityHelper::class);
        $this->securityHelper->method('validateCsrfToken')
            ->willReturn(true);

        $this->server['REQUEST_METHOD'] = 'POST';
        $this->server['REMOTE_ADDR'] = '10.0.0.200';
        $this->post['csrf_token'] = 'valid_token';
        $this->post['username'] = 'username';
        $this->post['password'] = '';

        ob_start();
        $handler = new LoginHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->post,
            $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $jsonOutput = json_decode($output, true);

        $this->assertFalse($jsonOutput['success']);
        $this->assertStringContainsString("Password is required", $jsonOutput['message']);
    }

    public function testDatabaseErrorOnLoginReturnsError(): void
    {
        $this->session = new MockSession();
        $this->securityHelper = $this->createStub(SecurityHelper::class);
        $this->securityHelper->method('validateCsrfToken')
            ->willReturn(true);

        $this->server['REQUEST_METHOD'] = 'POST';
        $this->server['REMOTE_ADDR'] = '10.0.0.200';
        $this->post['csrf_token'] = 'valid_token';
        $this->post['username'] = 'username';
        $this->post['password'] = 'password';

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->will($this->throwException(new PDOException("Database error")));
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPDO')
            ->willReturn($pdo);

        $this->assertNull($this->session['user_id']);
        $this->assertNull($this->session['authenticated']);

        ob_start();
        $handler = new LoginHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->post,
            $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $jsonOutput = json_decode($output, true);

        $this->assertFalse($jsonOutput['success']);
        $this->assertStringContainsString("Database error occurred", $jsonOutput['message']);
        $this->assertNull($this->session['user_id']);
        $this->assertNull($this->session['authenticated']);
    }

    // Tests requiring a mock database

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testValidLoginSetsSessionAndReturnsSuccess(): void
    {
        $this->session = new MockSession();
        $this->securityHelper = $this->createStub(SecurityHelper::class);
        $this->securityHelper->method('validateCsrfToken')
            ->willReturn(true);

        $this->server['REQUEST_METHOD'] = 'POST';
        $this->server['REMOTE_ADDR'] = '10.0.0.200';
        $this->post['csrf_token'] = 'valid_token';
        $this->post['username'] = 'testuser';
        $this->post['password'] = 'testpass';

        $db = new MockPostgresDB();
        $this->pdo = $db->getPDO();
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);

        $this->assertNull($this->session['user_id']);
        $this->assertNull($this->session['authenticated']);

        ob_start();
        $handler = new LoginHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->post,
            $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $jsonOutput = json_decode($output, true);

        $this->assertTrue($jsonOutput['success']);
        $this->assertStringContainsString("Login successful", $jsonOutput['message']);
        $this->assertEquals(2, $this->session['user_id']);
        $this->assertTrue($this->session['authenticated']);
        $this->assertEquals('testuser', $this->session['username']);
        $this->assertEquals('/dashboard', $jsonOutput['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testNonExistentUserLoginReturnsError(): void
    {
        $this->session = new MockSession();
        $this->securityHelper = $this->createStub(SecurityHelper::class);
        $this->securityHelper->method('validateCsrfToken')
            ->willReturn(true);

        $this->server['REQUEST_METHOD'] = 'POST';
        $this->server['REMOTE_ADDR'] = '10.0.0.200';
        $this->post['csrf_token'] = 'valid_token';
        $this->post['username'] = 'nonexistent';
        $this->post['password'] = 'testpass';

        $db = new MockPostgresDB();
        $this->pdo = $db->getPDO();
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);

        $this->assertNull($this->session['user_id']);
        $this->assertNull($this->session['authenticated']);

        ob_start();
        $handler = new LoginHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->post,
            $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $jsonOutput = json_decode($output, true);

        $this->assertFalse($jsonOutput['success']);
        $this->assertStringContainsString("Invalid username or password", $jsonOutput['message']);
        $this->assertNull($this->session['user_id']);
        $this->assertNull($this->session['authenticated']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testWrongPasswordLoginReturnsError(): void
    {
        $this->session = new MockSession();
        $this->securityHelper = $this->createStub(SecurityHelper::class);
        $this->securityHelper->method('validateCsrfToken')
            ->willReturn(true);

        $this->server['REQUEST_METHOD'] = 'POST';
        $this->server['REMOTE_ADDR'] = '10.0.0.200';
        $this->post['csrf_token'] = 'valid_token';
        $this->post['username'] = 'testuser';
        $this->post['password'] = 'wrongpass';

        $db = new MockPostgresDB();
        $this->pdo = $db->getPDO();
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);

        $this->assertNull($this->session['user_id']);
        $this->assertNull($this->session['authenticated']);

        ob_start();
        $handler = new LoginHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->post,
            $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $jsonOutput = json_decode($output, true);

        $this->assertFalse($jsonOutput['success']);
        $this->assertStringContainsString("Invalid username or password", $jsonOutput['message']);
        $this->assertNull($this->session['user_id']);
        $this->assertNull($this->session['authenticated']);
    }
}
