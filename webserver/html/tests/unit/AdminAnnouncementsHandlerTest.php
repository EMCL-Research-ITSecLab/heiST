<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\TestCase;

class AdminAnnouncementsHandlerTest extends TestCase
{
    private PDO $pdo;

    private array $config;
    private array $generalConfig;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;

    private ISession $session;
    private IServer $server;
    private IGet $get;

    private ISystem $system;

    private $mockDB;

    private array $importanceLevels;
    private array $validCategories;

    public function setUp(): void
    {
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->logger = new MockLogger();

        $this->session = new MockSession();
        $this->server = new MockServer();
        $this->get = new MockGet();

        $this->system = new SystemWrapper();

        $this->config = require __DIR__ . '/../../config/backend.config.php';
        $this->generalConfig = json_decode(file_get_contents(__DIR__ . '/../../config/general.config.json'), true);

        // Mock PDO for database interactions
        $this->mockDB = null;

        $this->importanceLevels = $this->config['filters']['IMPORTANCE_LEVELS'];
        $this->validCategories = $this->config['announcement']['VALID_CATEGORIES'];
    }

    public function testInvalidSessionThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Unauthorized');
        $this->expectExceptionCode(401);

        new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
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

        $idToAttributesMapping = [];

        foreach ($this->validCategories as $category) {
            foreach ($this->importanceLevels as $importanceLevel) {
                if($importanceLevel === 'all')
                    continue;

                $title = "Test Announcement {$category} {$importanceLevel}";
                $content = "This is a test announcement for category {$category} with importance {$importanceLevel}.";
                $author = 'admin';

                $stmt = $this->pdo->prepare("
                    INSERT INTO announcements (title, content, importance, category, author)
                    VALUES (:title, :content, :importance, :category, :author)
                    RETURNING id;
                ");
                $stmt->execute([
                    ':title' => $title,
                    ':content' => $content,
                    ':importance' => $importanceLevel,
                    ':category' => $category,
                    ':author' => $author
                ]);
                $id = $stmt->fetchColumn();

                $idToAttributesMapping[$id] = [
                    'title' => $title,
                    'content' => $content,
                    'importance' => $importanceLevel,
                    'category' => $category,
                    'author' => $author
                ];
            }
        }

        return $idToAttributesMapping;
    }

    public function testInvalidCsrfTokenThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid CSRF token');
        $this->expectExceptionCode(403);

        new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
    }

    public function testDatabaseErrorDuringRequestHandlingThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'list';

        $stmtList = $this->createStub(PDOStatement::class);
        $stmtList->method('execute')->willReturn(true);
        $stmtList->method('fetchColumn')->willThrowException(new PDOException("Simulated database error"));

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturnOnConsecutiveCalls( $stmtList);
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Database error occurred');
        $this->expectExceptionCode(500);

        $handler->handleRequest();
    }

    public function testNonAdminAccessThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Unauthorized - Admin access only');
        $this->expectExceptionCode(403);

        new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testInvalidActionThrowsException(): void
    {
        $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'invalid_action';

        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid action');
        $this->expectExceptionCode(400);

        $handler->handleRequest();
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCreateNoTitleThrowsException(): void
    {
        $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'create';

        $postData = [
            'title' => '',
            'content' => 'This is a new announcement.',
            'importance' => $this->importanceLevels[1],
            'category' => $this->validCategories[1]
        ];

        $jsonInput = json_encode($postData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertFalse($data['success']);
        $this->assertStringContainsString('Validation failed', $data['message']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCreateTooLongTitleThrowsException(): void
    {
        $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'create';

        $postData = [
            'title' => str_repeat('A', $this->generalConfig['announcement']['MAX_ANNOUNCEMENT_NAME_LENGTH'] + 1),
            'content' => 'This is a new announcement.',
            'importance' => $this->importanceLevels[1],
            'category' => $this->validCategories[1]
        ];

        $jsonInput = json_encode($postData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertFalse($data['success']);
        $this->assertStringContainsString('Validation failed', $data['message']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCreateTooLongShortDescriptionThrowsException(): void
    {
        $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'create';

        $postData = [
            'title' => 'Test Title',
            'short_description' => str_repeat('A', $this->generalConfig['announcement']['MAX_ANNOUNCEMENT_SHORT_DESCRIPTION_LENGTH'] + 1),
            'content' => 'This is a new announcement.',
            'importance' => $this->importanceLevels[1],
            'category' => $this->validCategories[1]
        ];

        $jsonInput = json_encode($postData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertFalse($data['success']);
        $this->assertStringContainsString('Validation failed', $data['message']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCreateNoContentThrowsException(): void
    {
        $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'create';

        $postData = [
            'title' => 'Test Title',
            'content' => '',
            'importance' => $this->importanceLevels[1],
            'category' => $this->validCategories[1]
        ];

        $jsonInput = json_encode($postData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertFalse($data['success']);
        $this->assertStringContainsString('Validation failed', $data['message']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCreateTooLongContentThrowsException(): void
    {
        $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'create';

        $postData = [
            'title' => 'Test Title',
            'content' => str_repeat('A', $this->generalConfig['announcement']['MAX_ANNOUNCEMENT_DESCRIPTION_LENGTH'] + 1),
            'importance' => $this->importanceLevels[1],
            'category' => $this->validCategories[1]
        ];

        $jsonInput = json_encode($postData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertFalse($data['success']);
        $this->assertStringContainsString('Validation failed', $data['message']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCreateInvalidCategoryThrowsException(): void
    {
        $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'create';

        $postData = [
            'title' => 'Test Title',
            'content' => 'This is a new announcement.',
            'importance' => $this->importanceLevels[1],
            'category' => 'invalid_category'
        ];

        $jsonInput = json_encode($postData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertFalse($data['success']);
        $this->assertStringContainsString('Validation failed', $data['message']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCreateInvalidImportanceThrowsException(): void
    {
        $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'create';

        $postData = [
            'title' => 'Test Title',
            'content' => 'This is a new announcement.',
            'importance' => 'invalid_importance',
            'category' => $this->validCategories[1]
        ];

        $jsonInput = json_encode($postData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertFalse($data['success']);
        $this->assertStringContainsString('Validation failed', $data['message']);
    }
    
    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCreateAnnouncementMalformedJsonThrowsException(): void
    {
        $this->requireMockDB();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'create';

        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn("
        {
            'title': 'Malformed JSON': 'Test',
            'content': 'This is malformed JSON'
        ");

        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid JSON data');
        $this->expectExceptionCode(400);

        $handler->handleRequest();
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCreateAnnouncement(): void
    {
        $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'create';

        $postData = [
            'title' => 'New Announcement',
            'content' => 'This is a new announcement.',
            'importance' => $this->importanceLevels[1],
            'category' => $this->validCategories[1]
        ];

        $jsonInput = json_encode($postData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertTrue($data['success']);
        $this->assertStringContainsString('Announcement created successfully', $data['message']);
        $this->assertArrayHasKey('id', $data);

        $stmt = $this->pdo->prepare("SELECT * FROM announcements WHERE id = :id");
        $stmt->execute([':id' => $data['id']]);
        $announcement = $stmt->fetch(PDO::FETCH_ASSOC);

        $this->assertNotFalse($announcement);
        $this->assertEquals($postData['title'], $announcement['title']);
        $this->assertEquals($postData['content'], $announcement['content']);
        $this->assertEquals($postData['importance'], $announcement['importance']);
        $this->assertEquals($postData['category'], $announcement['category']);
        $this->assertEquals('admin', $announcement['author']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testlistAnnouncements(): void
    {
        $idToAttributesMapping = $this->setupMockData();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'list';

        $page = 1;

        $receivedAnnouncements = [];

        do {
            $this->get['page'] = $page;

            ob_start();
            $handler = new AdminAnnouncementsHandler(
                $this->config,
                $this->generalConfig,
                $this->databaseHelper,
                $this->securityHelper,
                $this->logger,
                $this->session,
                $this->server,
                $this->get,
                $this->system
            );
            $handler->handleRequest();
            $response = ob_get_clean();
            $data = json_decode($response, true);

            $this->assertTrue($data['success']);
            $this->assertArrayHasKey('announcements', $data['data']);
            $this->assertArrayHasKey('total', $data['data']);

            $receivedAnnouncements = array_merge($receivedAnnouncements, $data['data']['announcements']);

            $page++;
            $total = $data['data']['total'];
        } while (count($receivedAnnouncements) < $total);

        foreach ($receivedAnnouncements as $announcement) {
            $id = $announcement['id'];
            $this->assertArrayHasKey($id, $idToAttributesMapping);
            $expected = $idToAttributesMapping[$id];
            $this->assertEquals($expected['title'], $announcement['title']);
            $this->assertEquals($expected['content'], $announcement['content']);
            $this->assertEquals($expected['importance'], $announcement['importance']);
            $this->assertEquals($expected['category'], $announcement['category']);
            $this->assertEquals($expected['author'], $announcement['author']);
        }

        foreach ($idToAttributesMapping as $id => $expected) {
            $found = false;
            foreach ($receivedAnnouncements as $announcement) {
                if ($announcement['id'] === $id) {
                    $found = true;
                    break;
                }
            }

            $this->assertTrue($found, "Announcement with ID {$id} not found in response");
        }
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testUpdateAnnouncement(): void
    {
        $idToAttributesMapping = $this->setupMockData();
        $announcementId = array_key_first($idToAttributesMapping);

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'update';

        $updatedData = [
            'id' => $announcementId,
            'title' => 'Updated Announcement Title',
            'content' => 'This is the updated content of the announcement.',
            'importance' => 'critical',
            'category' => 'security'
        ];

        $jsonInput = json_encode($updatedData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertTrue($data['success']);

        $stmt = $this->pdo->prepare("SELECT * FROM announcements WHERE id = :id");
        $stmt->execute([':id' => $announcementId]);
        $announcement = $stmt->fetch(PDO::FETCH_ASSOC);

        $this->assertNotFalse($announcement);
        $this->assertEquals($updatedData['title'], $announcement['title']);
        $this->assertEquals($updatedData['content'], $announcement['content']);
        $this->assertEquals($updatedData['importance'], $announcement['importance']);
        $this->assertEquals($updatedData['category'], $announcement['category']);
        $this->assertEquals('admin', $announcement['author']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testUpdateNonExistentAnnouncementThrowsException(): void
    {
        $idToAttributesMapping = $this->setupMockData();
        $announcementId = 99999; // Non-existent ID

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'update';

        $updatedData = [
            'id' => $announcementId,
            'title' => 'Updated Announcement Title',
            'content' => 'This is the updated content of the announcement.',
            'importance' => 'critical',
            'category' => 'security'
        ];

        $jsonInput = json_encode($updatedData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Announcement not found');
        $this->expectExceptionCode(404);

        $handler->handleRequest();

    }


    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testDeleteAnnouncement(): void
    {
        $idToAttributesMapping = $this->setupMockData();
        $announcementId = array_key_first($idToAttributesMapping);

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'delete';

        $postData = ['id' => $announcementId];
        $jsonInput = json_encode($postData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        $stmt = $this->pdo->prepare("SELECT * FROM announcements WHERE id = :id");
        $stmt->execute([':id' => $announcementId]);
        $announcement = $stmt->fetch(PDO::FETCH_ASSOC);
        $this->assertNotFalse($announcement);

        ob_start();
        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );
        $handler->handleRequest();
        $response = ob_get_clean();
        $data = json_decode($response, true);

        $this->assertTrue($data['success']);
        $this->assertStringContainsString('Announcement deleted successfully', $data['message']);

        $stmt = $this->pdo->prepare("SELECT * FROM announcements WHERE id = :id");
        $stmt->execute([':id' => $announcementId]);
        $announcement = $stmt->fetch(PDO::FETCH_ASSOC);

        $this->assertFalse($announcement);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testDeleteNoAnnouncementIdThrowsException(): void
    {
        $idToAttributesMapping = $this->setupMockData();
        $announcementId = array_key_first($idToAttributesMapping);

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'delete';

        $jsonInput = json_encode([]);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        $stmt = $this->pdo->prepare("SELECT * FROM announcements WHERE id = :id");
        $stmt->execute([':id' => $announcementId]);
        $announcement = $stmt->fetch(PDO::FETCH_ASSOC);
        $this->assertNotFalse($announcement);

        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Missing announcement ID');
        $this->expectExceptionCode(400);

        $handler->handleRequest();
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testUpdateNoAnnouncementIdThrowsException(): void
    {
        $idToAttributesMapping = $this->setupMockData();
        $announcementId = array_key_first($idToAttributesMapping);

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);
        $this->securityHelper->method('validateAdminAccess')->willReturn(true);

        $this->session['user_id'] = 1;
        $this->session['username'] = 'admin';

        $this->get['action'] = 'update';

        $updatedData = [
            'title' => 'Updated Announcement Title',
            'content' => 'This is the updated content of the announcement.',
            'importance' => 'critical',
            'category' => 'security'
        ];

        $jsonInput = json_encode($updatedData);
        $this->system = $this->createStub(ISystem::class);
        $this->system->method('file_get_contents')->willReturn($jsonInput);

        $stmt = $this->pdo->prepare("SELECT * FROM announcements WHERE id = :id");
        $stmt->execute([':id' => $announcementId]);
        $announcement = $stmt->fetch(PDO::FETCH_ASSOC);
        $this->assertNotFalse($announcement);

        $handler = new AdminAnnouncementsHandler(
            $this->config,
            $this->generalConfig,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get,
            $this->system
        );

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Missing announcement ID');
        $this->expectExceptionCode(400);

        $handler->handleRequest();
    }


}

