<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\TestCase;

class ChallengeHandlerTest extends TestCase
{
    private PDO $pdo;
    private ?int $userId = 1;
    private array $config;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ICurlHelper $curlHelper;
    private IAuthHelper $authHelper;
    private IChallengeHelper $challengeHelper;
    private ILogger $logger;

    private ISession $session;
    private IServer $server;
    private IGet $get;
    private IEnv $env;

    private ISystem $system;

    public function setUp(): void
    {
        $this->config = require __DIR__ . '/../../config/backend.config.php';

        $this->session = new MockSession();
        $this->server = new MockServer();
        $this->get = new MockGet();
        $this->env = new MockEnv();

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->curlHelper = $this->createStub(ICurlHelper::class);
        $this->authHelper = $this->createStub(IAuthHelper::class);
        $this->challengeHelper = $this->createStub(IChallengeHelper::class);
        $this->logger = new MockLogger();

        $this->system = $this->createStub(ISystem::class);
    }

    public function testInvalidSessionThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Unauthorized - Please login');
        $this->expectExceptionCode(401);

        new ChallengeHandler(
            $this->config,
            $this->databaseHelper,
            $this->securityHelper,
            $this->curlHelper,
            $this->authHelper,
            $this->challengeHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system,
            $this->env
        );
    }

    public function testInvalidCsrfTokenThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid CSRF token');
        $this->expectExceptionCode(403);

        new ChallengeHandler(
            $this->config,
            $this->databaseHelper,
            $this->securityHelper,
            $this->curlHelper,
            $this->authHelper,
            $this->challengeHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system,
            $this->env
        );
    }

    public function testInvalidRequestMethodThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->server['REQUEST_METHOD'] = 'PUT';

        ob_start();
        $handler = new ChallengeHandler(
            $this->config,
            $this->databaseHelper,
            $this->securityHelper,
            $this->curlHelper,
            $this->authHelper,
            $this->challengeHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system,
            $this->env
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Method not allowed', $json['message']);
        $this->assertEquals(405, $json['error_code']);
    }

    public function testInvalidJsonInputOnPostRequestThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->server['REQUEST_METHOD'] = 'POST';

        // Simulate invalid JSON input
        $invalidJson = "{invalidJson: true"; // Missing closing brace
        $this->system->method('file_get_contents')->willReturn($invalidJson);

        ob_start();
        $handler = new ChallengeHandler(
            $this->config,
            $this->databaseHelper,
            $this->securityHelper,
            $this->curlHelper,
            $this->authHelper,
            $this->challengeHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system,
            $this->env
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Invalid JSON input', $json['message']);
        $this->assertEquals(400, $json['error_code']);
    }


}