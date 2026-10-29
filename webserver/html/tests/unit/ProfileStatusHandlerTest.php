<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\TestCase;

class ProfileStatusHandlerTest extends TestCase
{
    private PDO $pdo;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;

    private ISession $session;
    private IServer $server;
    private $mockDB;

    public function setUp(): void {
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->logger = new MockLogger();

        $this->session = new MockSession();
        $this->server = new MockServer();

        $this->mockDB = null;
        $this->pdo = $this->createStub(PDO::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);
    }

    private function requireMockDB(): void {
        $this->mockDB = new MockPostgresDB();
        $this->pdo = $this->mockDB->getPDO();
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);
    }

    public function testFailedInitSecureSessionThrowsException(): void {
        $securityHelper = $this->createStub(ISecurityHelper::class);
        $securityHelper->method('initSecureSession')->will($this->throwException(new Exception('Session init failed')));

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Internal Server Error');
        $this->expectExceptionCode(500);

        new ProfileStatusHandler(
            $this->databaseHelper,
            $securityHelper,
            $this->logger,
            $this->session,
            $this->server
        );
    }

    public function testInvalidRequestMethodThrowsException(): void {
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->expectException(CustomException::class);
        $this->expectExceptionMessage('Method not allowed');
        $this->expectExceptionCode(405);

        new ProfileStatusHandler(
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server
        );
    }

    public function testErrorDuringRequestHandlingDueToNonExistentUserThrowsExceptions(): void {
        $pdo = $this->createStub(PDO::class);
        $stmt = $this->createStub(PDOStatement::class);
        $databaseHelper = $this->createStub(IDatabaseHelper::class);
        $stmt->method('execute')->willReturn(true);
        $stmt->method('fetch')->willReturn(null);
        $pdo->method('prepare')->willReturn($stmt);
        $databaseHelper->method('getPDO')->willReturn($pdo);

        $server = new MockServer();
        $server['REQUEST_METHOD'] = 'GET';

        $securityHelper = $this->createStub(ISecurityHelper::class);
        $securityHelper->method('validateSession')->willReturn(true);

        $session = new MockSession();
        $session['user_id'] = 999;

        $handler = new ProfileStatusHandler(
            $databaseHelper,
            $securityHelper,
            $this->logger,
            $session,
            $server
        );

        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();

        $this->assertJson($output);
        $response = json_decode($output, true);

        $this->assertFalse($response['success']);
        $this->assertEquals('User not found', $response['message']);
    }

    public function testDatabaseErrorThrowsException(): void {
        $pdo = $this->createStub(PDO::class);
        $stmt = $this->createStub(PDOStatement::class);
        $databaseHelper = $this->createStub(IDatabaseHelper::class);
        $stmt->method('execute')->will($this->throwException(new PDOException('Database error')));
        $pdo->method('prepare')->willReturn($stmt);
        $databaseHelper->method('getPDO')->willReturn($pdo);

        $server = new MockServer();
        $server['REQUEST_METHOD'] = 'GET';

        $securityHelper = $this->createStub(ISecurityHelper::class);
        $securityHelper->method('validateSession')->willReturn(true);

        $session = new MockSession();
        $session['user_id'] = 1;

        $handler = new ProfileStatusHandler(
            $databaseHelper,
            $securityHelper,
            $this->logger,
            $session,
            $server
        );

        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();

        $this->assertJson($output);
        $response = json_decode($output, true);

        $this->assertFalse($response['success']);
        $this->assertEquals('An internal server error occurred', $response['message']);
    }

    // Tests requiring a mock DB

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testSuccessfulRequestHandlingForLoggedInUser(): void {
        $this->requireMockDB();

        $server = new MockServer();
        $server['REQUEST_METHOD'] = 'GET';

        $securityHelper = $this->createStub(ISecurityHelper::class);
        $securityHelper->method('validateSession')->willReturn(true);

        $session = new MockSession();
        $session['user_id'] = 1;

        $databaseHelper = $this->createStub(IDatabaseHelper::class);
        $databaseHelper->method('getPDO')->willReturn($this->pdo);

        $handler = new ProfileStatusHandler(
            $databaseHelper,
            $securityHelper,
            $this->logger,
            $session,
            $server
        );

        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();

        $this->assertJson($output);
        $response = json_decode($output, true);

        $this->assertTrue($response['success']);
        $this->assertTrue($response['data']['is_logged_in']);
        $this->assertStringMatchesFormat('/assets/avatars/avatar%d.png', $response['data']['avatar_url']);
        $this->assertTrue($response['data']['is_admin']);
    }
}