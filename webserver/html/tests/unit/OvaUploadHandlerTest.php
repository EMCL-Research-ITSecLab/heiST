<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

class OvaUploadHandlerTest extends TestCase
{
    private PDO $pdo;

    private array $config;
    private array $generalConfig;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;
    private ICurlHelper $curlHelper;
    private IAuthHelper $authHelper;
    private IOvaValidator $ovaValidator;

    private ISession $session;
    private IServer $server;
    private IGet $get;
    private IPost $post;
    private IFiles $files;
    private IEnv $env;

    private ISystem $system;

    private $mockDB;
    private int $userId = 1;


    public function setUp(): void
    {
        // Initialize configuration arrays
        $this->config = require __DIR__ . '/../../config/backend.config.php';
        $this->generalConfig = json_decode(file_get_contents(__DIR__ . '/../../config/general.config.json'), true);

        $this->pdo = $this->createStub(PDO::class);
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);

        // Mock dependencies
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->logger = new MockLogger();
        $this->curlHelper = $this->createStub(ICurlHelper::class);
        $this->authHelper = $this->createStub(IAuthHelper::class);
        $this->ovaValidator = $this->createStub(IOvaValidator::class);

        $this->session = new MockSession();
        $this->server = new MockServer();
        $this->get = new MockGet();
        $this->post = new MockPost();
        $this->post['guest_os'] = 'linux';
        $this->post['fileSize'] = 123456;
        $this->post['totalChunks'] = 1;
        $this->post['chunkIndex'] = 0;
        $this->files = new MockFiles();
        $this->env = new MockEnv();

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('mkdir')->willReturn(true);
        $this->system->method('file_get_contents')->willReturn('{}');

        $this->mockDB = null;
    }

    private function requireMockDB(): void
    {
        $this->mockDB = new MockPostgresDB();
        $this->pdo = $this->mockDB->getPDO();
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);
    }

    private function setupMockData(): array
    {
        $this->requireMockDB();

        $disk_files = [
            [
                'user_id' => $this->userId,
                'display_name' => 'test1',
                'proxmox_filename' => 'vm-100-disk-0.ova'
            ],
            [
                'user_id' => $this->userId,
                'display_name' => 'test2',
                'proxmox_filename' => 'vm-101-disk-0.ova'
            ],
            [
                'user_id' => $this->userId,
                'display_name' => 'test3',
                'proxmox_filename' => 'vm-102-disk-0.ova'
            ]
        ];

        foreach ($disk_files as &$disk_file) {
            $stmt = $this->pdo->prepare("
                INSERT INTO disk_files (user_id, display_name, proxmox_filename)
                VALUES ({$disk_file['user_id']}, '{$disk_file['display_name']}', '{$disk_file['proxmox_filename']}')
                RETURNING id
            ");
            $stmt->execute();
            $disk_file['id'] = $stmt->fetchColumn();
        }

        return $disk_files;
    }

    public function testInitSecureSessionThrowsException(): void
    {
        $this->securityHelper->method('initSecureSession')->willThrowException(new Exception());

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Internal Server Error');
        $this->expectExceptionCode(500);

        new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
    }

    public function testInvalidSessionThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(false);

        $this->expectException(CustomException::class);
        $this->expectExceptionMessage('Unauthorized - Please login');
        $this->expectExceptionCode(401);

        new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
    }

    public function testInvalidCsrfTokenThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(false);

        $this->expectException(CustomException::class);
        $this->expectExceptionMessage('Invalid CSRF token');
        $this->expectExceptionCode(403);

        new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
    }

    public function testNonAdminAccessThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(false);

        $this->expectException(CustomException::class);
        $this->expectExceptionMessage('Unauthorized - Admin access required');
        $this->expectExceptionCode(403);

        new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
    }

    public function testCreateUploadDirErrorThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_exists')->willReturn(false);
        $this->system->method('mkdir')->willReturn(false);
        $this->system->method('file_get_contents')->willReturn('null');

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('System configuration error', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testInvalidMethodRequestThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'INVALID';

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Method not allowed', $json['message']);
        $this->assertEquals(405, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testDeleteRequestWithMalformedJsonThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'DELETE';

        $malformedJson = '{"ova_id": 123';
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($malformedJson);

        $this->expectException(CustomException::class);
        $this->expectExceptionMessage('Invalid JSON data');
        $this->expectExceptionCode(400);

        new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
    }

    public function testInvalidActionOnGetRequestThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'GET';
        $this->get['action'] = 'invalid_action';

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Invalid request', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testInvalidActionOnDeleteRequestThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'DELETE';
        $this->get['action'] = 'invalid_action';

        $malformedJson = '{"ova_id": 123}';
        $this->system->method('file_get_contents')->willReturn($malformedJson);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Invalid request', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testDatabaseErrorDuringListActionThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'GET';
        $this->get['action'] = 'list';

        $this->pdo->method('prepare')->willThrowException(new PDOException("Database error"));

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Could not retrieve file list', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testDirectUploadCancelledThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->files['ova_file'] = [
            'name' => 'test.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_PARTIAL,
            'size' => 123456
        ];

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Upload was cancelled or timed out', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testDirectUploadErrorThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->files['ova_file'] = [
            'name' => 'test.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_NO_FILE,
            'size' => 0
        ];

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File upload failed', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testInvalidFiletypeThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->files['ova_file'] = [
            'name' => 'test.txt',
            'type' => 'text/plain',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Invalid file type', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testTooLargeFileThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );

        $this->files['ova_file'] = [
            'name' => 'test.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => $this->generalConfig['upload']['MAX_FILE_SIZE'] + 1
        ];

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File too large', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testMoveErrorOnDirectUploadThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(false);

        $this->files['ova_file'] = [
            'name' => 'test.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File processing error', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testConnectionAbortedOnDirectUploadThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(true);
        $this->system->method('connection_aborted')->willReturn(1);

        $this->files['ova_file'] = [
            'name' => 'test.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Upload cancelled', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testInvalidOvaErrorThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(true);
        $this->system->method('connection_aborted')->willReturn(0);

        $this->files['ova_file'] = [
            'name' => 'test.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        $this->ovaValidator->method('validate')->willThrowException(new Exception());

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testDatabaseErrorDuringCheckDuplicateFilenameInDirectUploadThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(true);
        $this->system->method('connection_aborted')->willReturn(0);

        $this->files['ova_file'] = [
            'name' => 'test.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        $this->pdo->method('prepare')->willThrowException(new PDOException("Database error"));

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Could not verify file name', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testDatabaseErrorDuringInsertFileMetadataDuringDirectUploadThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(true);
        $this->system->method('connection_aborted')->willReturn(0);

        $stmt1 = $this->createStub(PDOStatement::class);
        $stmt1->method('execute')->willReturn(true);
        $stmt1->method('fetch')->willReturn(['count' => 0]);

        $stmt2 = $this->createStub(PDOStatement::class);
        $stmt2->method('execute')->willThrowException(new PDOException());

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturnOnConsecutiveCalls($stmt1, $stmt2);
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        $this->files['ova_file'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 200,
            'response' => json_encode([])
        ]);

        $this->pdo->method('prepare')->willThrowException(new PDOException("Database error"));

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Could not save file information', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testChunkedUploadInvalidPhaseThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'invalid_phase';

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Invalid upload request', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testNoChunkDataThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'chunk';
        $this->post['fileName'] = 'new.ova';

        $this->files['chunk'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_NO_FILE,
            'size' => 250,
        ];


        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            json_encode(['userId' => 1, 'receivedChunks' => 0]),
            false
        );

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File read failed', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testOpenCombinedFileErrorThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'chunk';
        $this->post['fileName'] = 'new.ova';

        $this->files['chunk'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 250,
        ];

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            json_encode(['userId' => 1, 'receivedChunks' => 0]),
            'chunk data'
        );
        $this->system->method('fopen')->willReturn(false);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File open failed', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testFseekErrorThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'chunk';
        $this->post['fileName'] = 'new.ova';

        $this->files['chunk'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 250,
        ];

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            json_encode(['userId' => 1, 'receivedChunks' => 0]),
            'chunk data'
        );
        $this->system->method('fopen')->willReturn(fopen('php://memory', 'r+'));
        $this->system->method('fseek')->willReturn(-1);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File seek failed', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testFwriteErrorThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'chunk';
        $this->post['fileName'] = 'new.ova';

        $this->files['chunk'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 250,
        ];

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            json_encode(['userId' => 1, 'receivedChunks' => 0]),
            'chunk data'
        );
        $this->system->method('fopen')->willReturn(fopen('php://memory', 'r+'));
        $this->system->method('fseek')->willReturn(0);
        $this->system->method('fwrite')->willReturn(false);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File write failed', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testUpdateUploadMetadataErrorThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'chunk';
        $this->post['fileName'] = 'new.ova';

        $this->files['chunk'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 250,
        ];

        $stmt = $this->createStub(PDOStatement::class);
        $stmt->method('execute')->willThrowException(new PDOException("Database error"));

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturn($stmt);
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            json_encode(['userId' => 1, 'receivedChunks' => 0]),
            'chunk data'
        );
        $this->system->method('fopen')->willReturn(fopen('php://memory', 'r+'));
        $this->system->method('fseek')->willReturn(0);
        $this->system->method('fwrite')->willReturn(250);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Could not update upload status', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testChunkUploadWorks(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'chunk';
        $this->post['fileName'] = 'new.ova';

        $this->files['chunk'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 250,
        ];

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            json_encode(['userId' => 1, 'receivedChunks' => 0]),
            'chunk data'
        );
        $this->system->method('fopen')->willReturn(fopen('php://memory', 'r+'));
        $this->system->method('fseek')->willReturn(0);
        $this->system->method('fwrite')->willReturn(250);
        $this->system->method('unlink')->willReturn(true);
        $this->system->method('file_put_contents')->willReturn(250);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
    }

    public function testNonExistentMetaFileOnChunkedCancellationWorks(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'cancel';
        $this->post['fileName'] = 'new.ova';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_exists')->willReturnOnConsecutiveCalls(true, false);
        $this->system->method('file_get_contents')->willReturn(json_encode(null));

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
        $this->assertArrayNotHasKey('message', $json);
        $this->assertArrayNotHasKey('error_code', $json);
        $this->assertArrayNotHasKey('redirect', $json);
    }

    public function testMetaFileAndPostUserIdMismatchOnChunkedCancellationThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'cancel';
        $this->post['fileName'] = 'new.ova';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );

        $meta = json_encode([
            'userId' => 2,
            'receivedChunks' => 1,
            'totalChunks' => 2,
            'fileName' => 'new.ova'
        ]);

        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            $meta
        );

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Unauthorized cancellation', $json['message']);
        $this->assertEquals(403, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testDeleteFromProxmoxErrorOnCancellationIsIgnored(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'cancel';
        $this->post['fileName'] = 'new.ova';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );

        $meta = json_encode([
            'userId' => 1,
            'receivedChunks' => 1,
            'totalChunks' => 2,
            'fileName' => 'new.ova',
            'proxmoxFilename' => 'vzdump-qemu-100-2023_10_01-12_00_00.vma.gz'
        ]);

        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            $meta
        );
        $this->system->method('glob')->willReturn(['/tmp/upload_0_part1']);
        $this->system->method('unlink')->willReturn(true);

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 500,
            'response' => json_encode(['errors' => 'Internal Server Error'])
        ]);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
        $this->assertArrayNotHasKey('message', $json);
        $this->assertArrayNotHasKey('error_code', $json);
        $this->assertArrayNotHasKey('redirect', $json);
    }

    public function testDeleteActionNoOvaIdThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'DELETE';

        $this->get['action'] = 'delete';

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Missing file ID', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testDatabaseErrorDuringDeleteFromDatabaseInDeleteActionThrowsException(): void
    {
        $ova_id = 1;
        $proxmox_filename = 'vzdump-qemu-100-2023_10_01-12_00_00.vma.gz';
        $display_name = 'test.ova';

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = $this->userId;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'DELETE';

        $this->get['action'] = 'delete';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn(json_encode([
            'ova_id' => "$ova_id",
            'proxmox_filename' => "$proxmox_filename",
            'display_name' => "$display_name",
            'user_id' => $this->userId
        ]));
        $this->system->method('file_exists')->willReturn(true);

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 200,
            'response' => json_encode([])
        ]);

        $fetchStmt = $this->createStub(PDOStatement::class);
        $fetchStmt->method('execute')->willReturn(true);
        $fetchStmt->method('fetchColumn')->willReturn($proxmox_filename);

        $deleteStmt = $this->createStub(PDOStatement::class);
        $deleteStmt->method('execute')->willThrowException(new PDOException());

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturnOnConsecutiveCalls($fetchStmt, $deleteStmt);
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Could not complete file deletion', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testDatabaseErrorDuringDeleteActionThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'DELETE';

        $this->get['action'] = 'delete';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn(json_encode([
            'ova_id' => 'some-id',
            'proxmox_filename' => 'vzdump-qemu-100-2023_10_01-12_00_00.vma.gz',
            'display_name' => 'test.ova',
            'status' => 'completed',
            'uploaded_at' => '2023-10-01 12:00:00',
            'user_id' => 1
        ]));
        $this->system->method('file_exists')->willReturn(true);


        $stmt = $this->createStub(PDOStatement::class);
        $stmt->method('execute')->willReturn(true);
        $stmt->method('fetchColumn')->willThrowException(new PDOException());
        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturn($stmt);
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPdo')->willReturn($pdo);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Could not retrieve file information', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testErrorOnCreateUploadMetadataThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'init';
        $this->post['fileName'] = 'new.ova';

        $stmt = $this->createStub(PDOStatement::class);
        $stmt->method('execute')->willReturn(true);
        $stmt->method('fetch')->willReturn([]);

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturn($stmt);
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            json_encode(['userId' => 1, 'receivedChunks' => 0])
        );
        $this->system->method('file_put_contents')->willReturn(false);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Could not initialize upload', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testNonExisttingMetaFileDuringChunkedUploadSessionValidationThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'chunk';
        $this->post['fileName'] = 'new.ova';

        $this->files['chunk'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 250,
        ];

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_exists')->willReturnOnConsecutiveCalls(true, false);
        $this->system->method('file_get_contents')->willReturn(json_encode(null));

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Upload session expired', $json['message']);
        $this->assertEquals(404, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    public function testUserIdMismatchInMetaFileAndSessionDuringChunkedUploadThrowsException(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'chunk';
        $this->post['fileName'] = 'new.ova';

        $this->files['chunk'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 250,
        ];

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );

        $meta = json_encode([
            'userId' => 2,
            'receivedChunks' => 1,
            'totalChunks' => 2,
            'fileName' => 'new.ova'
        ]);

        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            $meta
        );

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Upload session mismatch', $json['message']);
        $this->assertEquals(403, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    // Tests requiring mock data setup

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testDuplicateFilenameDuringDirectUploadThrowsException(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(true);
        $this->system->method('connection_aborted')->willReturn(0);

        $this->files['ova_file'] = [
            'name' => $disk_files[0]['display_name'] . '.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File name already exists', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testConnectionErrorOnUploadToProxmoxDuringDirectUploadThrowsException(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(true);
        $this->system->method('connection_aborted')->willReturn(0);

        $this->files['ova_file'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        $this->curlHelper->method('makeCurlRequest')->willReturn(null);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Server connection failed', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testUploadErrorOnUploadToProxmoxDuringDirectUploadThrowsException(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(true);
        $this->system->method('connection_aborted')->willReturn(0);

        $this->files['ova_file'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 500,
            'response' => json_encode(['errors' => 'Internal Server Error'])
        ]);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File processing failed', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testConnectionAbortedAfterUploadToProxmoxDuringDirectUploadThrowsException(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(true);
        $this->system->method('connection_aborted')->willReturnOnConsecutiveCalls(0, 1);

        $this->files['ova_file'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 200,
            'response' => json_encode([])
        ]);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Upload cancelled', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testDirectUploadWorks(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = $this->userId;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('move_uploaded_file')->willReturn(true);
        $this->system->method('connection_aborted')->willReturn(0, 0);

        $this->files['ova_file'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 200,
            'response' => json_encode([])
        ]);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
        $this->assertEquals('File uploaded successfully', $json['message']);
        $this->assertArrayNotHasKey('error_code', $json);
        $this->assertArrayNotHasKey('redirect', $json);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testListActionWorks(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = $this->userId;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'GET';
        $this->get['action'] = 'list';

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);
        $received_files = $json['ovas'];

        $this->assertTrue($json['success']);
        $this->assertCount(count($disk_files), $received_files);

        foreach ($disk_files as $disk_file) {
            $found = false;
            foreach ($received_files as $received_file) {
                if ($received_file['id'] === $disk_file['id']) {
                    $this->assertEquals($disk_file['display_name'], $received_file['display_name']);
                    $found = true;
                    break;
                }
            }
            $this->assertTrue($found, "Disk file with ID {$disk_file['id']} not found in response");
        }
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testChunkInitWorks(): void
    {
        $diskFiles = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        //$this->post['phase'] = 'init'; // 'init' is the default phase, tests the defaulting
        $this->post['fileName'] = 'new.ova';

        $this->files['ova_file'] = [
            'name' => 'new.ova',
            'type' => 'application/x-virtualbox-ova',
            'tmp_name' => '/tmp/phpYzdqkD',
            'error' => UPLOAD_ERR_OK,
            'size' => 123456
        ];

        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );
        $this->system->method('file_put_contents')->willReturn(123456);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
        $this->assertNotNull($json['uploadId']);
        $this->assertNotNull($json['chunkSize']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testNotAllChunksReceivedOnFinalizeThrowsException(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'finalize';
        $this->post['fileName'] = 'new.ova';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );

        $meta = json_encode([
            'userId' => 1,
            'receivedChunks' => 1,
            'totalChunks' => 2,
            'fileName' => 'new.ova'
        ]);

        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            $meta
        );
        $this->system->method('glob')->willReturn(['/tmp/upload_0_part1', '/tmp/upload_0_part2']);
        $this->system->method('unlink')->willReturnOnConsecutiveCalls(true, false);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Upload incomplete', $json['message']);
        $this->assertEquals(400, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCombinedFileDoesntExistsOnFinalizeThrowsException(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'finalize';
        $this->post['fileName'] = 'new.ova';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );

        $meta = json_encode([
            'userId' => 1,
            'receivedChunks' => 2,
            'totalChunks' => 2,
            'fileName' => 'new.ova'
        ]);

        $this->system->method('file_exists')->willReturnOnConsecutiveCalls(true, true, false, true, true, true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            $meta
        );
        $this->system->method('glob')->willReturn(['/tmp/upload_0_part1']);
        $this->system->method('unlink')->willReturn(true);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('Combined file missing', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testChunkedUploadFinalizeWorks(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'finalize';
        $this->post['fileName'] = 'new.ova';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );

        $meta = json_encode([
            'userId' => 1,
            'receivedChunks' => 2,
            'totalChunks' => 2,
            'fileName' => 'new.ova'
        ]);

        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            $meta,
            'chunk1data',
            'chunk2data'
        );
        $this->system->method('glob')->willReturn(['/tmp/upload_0_part1', '/tmp/upload_0_part2']);
        $this->system->method('unlink')->willReturn(true);
        $this->system->method('file_put_contents')->willReturn(123456);

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 200,
            'response' => json_encode([])
        ]);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
        $this->assertEquals('File uploaded successfully', $json['message']);
        $this->assertArrayNotHasKey('error_code', $json);
        $this->assertArrayNotHasKey('redirect', $json);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testProxmoxBackendErrorDuringUploadOnFinalizeThrowsException(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'POST';

        $this->post['uploadId'] = "0";
        $this->post['phase'] = 'finalize';
        $this->post['fileName'] = 'new.ova';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('pathinfo')->willReturnCallback(
            fn($path, $option) => pathinfo($path, $option)
        );

        $meta = json_encode([
            'userId' => 1,
            'receivedChunks' => 2,
            'totalChunks' => 2,
            'fileName' => 'new.ova'
        ]);

        $this->system->method('file_exists')->willReturn(true);
        $this->system->method('file_get_contents')->willReturnOnConsecutiveCalls(
            json_encode(null),
            $meta,
            'chunk1data',
            'chunk2data'
        );
        $this->system->method('glob')->willReturn(['/tmp/upload_0_part1', '/tmp/upload_0_part2']);
        $this->system->method('unlink')->willReturn(true);
        $this->system->method('file_put_contents')->willReturn(123456);

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 500,
            'response' => json_encode(['errors' => 'Internal Server Error'])
        ]);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File processing failed', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testDeleteActionForNonExistentFileThrowsException(): void
    {
        $disk_files = $this->setupMockData();

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'DELETE';

        $this->get['action'] = 'delete';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn(json_encode([
            'ova_id' => '9999',
            'proxmox_filename' => 'vzdump-qemu-100-2023_10_01-12_00_00.vma.gz',
            'display_name' => 'test.ova',
            'status' => 'completed',
            'uploaded_at' => '2023-10-01 12:00:00',
            'user_id' => 1
        ]));
        $this->system->method('file_exists')->willReturn(true);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File not found', $json['message']);
        $this->assertEquals(404, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testProxmoxBackendErrorDuringDeleteActionThrowsException(): void
    {
        $disk_files = $this->setupMockData();
        $disk_file = $disk_files[0];
        $ova_id = $disk_file['id'];
        $proxmox_filename = $disk_file['proxmox_filename'];
        $display_name = $disk_file['display_name'];

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = $this->userId;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'DELETE';

        $this->get['action'] = 'delete';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn(json_encode([
            'ova_id' => "$ova_id",
            'proxmox_filename' => "$proxmox_filename",
            'display_name' => "$display_name",
            'user_id' => $this->userId
        ]));
        $this->system->method('file_exists')->willReturn(true);

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 500,
            'response' => json_encode(['errors' => 'Internal Server Error'])
        ]);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertFalse($json['success']);
        $this->assertEquals('File deletion failed', $json['message']);
        $this->assertEquals(500, $json['error_code']);
        $this->assertEquals(null, $json['redirect']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testDeleteActionWorks(): void
    {
        $disk_files = $this->setupMockData();
        $disk_file = $disk_files[0];
        $ova_id = $disk_file['id'];
        $proxmox_filename = $disk_file['proxmox_filename'];
        $display_name = $disk_file['display_name'];

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = $this->userId;
        $this->session['username'] = 'admin';
        $this->session['authenticated'] = true;
        $this->server['REQUEST_METHOD'] = 'DELETE';

        $this->get['action'] = 'delete';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn(json_encode([
            'ova_id' => "$ova_id",
            'proxmox_filename' => "$proxmox_filename",
            'display_name' => "$display_name",
            'user_id' => $this->userId
        ]));
        $this->system->method('file_exists')->willReturn(true);

        $this->curlHelper->method('makeCurlRequest')->willReturn([
            'http_code' => 200,
            'response' => json_encode([])
        ]);

        ob_start();
        $handler = new OvaUploadHandler(
            config: $this->config,
            generalConfig: $this->generalConfig,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            curlHelper: $this->curlHelper,
            authHelper: $this->authHelper,
            ovaValidator: $this->ovaValidator,
            session: $this->session,
            server: $this->server,
            get: $this->get,
            post: $this->post,
            files: $this->files,
            env: $this->env,
            system: $this->system
        );
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
        $this->assertEquals('File deleted successfully', $json['message']);
        $this->assertArrayNotHasKey('error_code', $json);
        $this->assertArrayNotHasKey('redirect', $json);

        $stmt = $this->pdo->prepare('SELECT COUNT(*) as count FROM disk_files WHERE id = :id');
        $stmt->execute([':id' => $ova_id]);
        $result = $stmt->fetch(PDO::FETCH_ASSOC);
        $this->assertEquals(0, $result['count'], 'File record was not deleted from database');
    }
}



