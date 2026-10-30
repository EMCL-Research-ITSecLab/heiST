<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\TestCase;

class BadgesHandlerTest extends TestCase
{
    private PDO $pdo;
    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelperMock;
    private ILogger $loggerMock;
    private ISession $session;
    private IServer $server;
    private array $cookie = [];

    private array $config;

    private $mockDB;

    protected function setUp(): void
    {
        $this->mockDB = null;
        $this->pdo = $this->createStub(PDO::class);
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);        

        // Mocks
        $this->securityHelperMock = $this->createStub(ISecurityHelper::class);
        $this->loggerMock = new MockLogger();

        // Simple array-backed session/server
        $this->session = new MockSession();
        $this->server = new MockServer();

        $this->config = require __DIR__ . '/../../config/backend.config.php';

        // Default valid security/session
        $this->securityHelperMock->method('validateSession')->willReturn(true);
        $this->securityHelperMock->method('validateCsrfToken')->willReturn(true);

        $this->cookie['csrf_token'] = 'valid_token';
        $this->session['user_id'] = 1;
    }

    private function requireMockDB(): void {
        $this->mockDB = new MockPostgresDB();
        $this->pdo = $this->mockDB->getPDO();
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);
        $this->pdo->exec("DELETE FROM badges");
    }

    private function getHandler(): BadgesHandler
    {
        return new BadgesHandler(
            $this->config,
            $this->databaseHelper,
            $this->securityHelperMock,
            $this->loggerMock,
            $this->session,
            $this->server
        );
    }

    public function testInvalidSessionThrowsException()
    {
        $securityMock = $this->createStub(ISecurityHelper::class);
        $securityMock->method('validateSession')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Unauthorized');
        $this->expectExceptionCode(401);

        new BadgesHandler(
            $this->config,
            $this->databaseHelper,
            $securityMock,
            $this->loggerMock,
            $this->session,
            $this->server
        );
    }

    public function testInvalidCsrfTokenThrowsException()
    {
        $securityMock = $this->createStub(ISecurityHelper::class);
        $securityMock->method('validateSession')->willReturn(true);
        $securityMock->method('validateCsrfToken')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid CSRF token');
        $this->expectExceptionCode(403);

        new BadgesHandler(
            $this->config,
            $this->databaseHelper,
            $securityMock,
            $this->loggerMock,
            $this->session,
            $this->server
        );
    }

    public function testUnsetUserIDThrowsException()
    {
        $session = new MockSession();
        $session['user_id'] = null;

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('User identification failed');
        $this->expectExceptionCode(500);

        new BadgesHandler(
            $this->config,
            $this->databaseHelper,
            $this->securityHelperMock,
            $this->loggerMock,
            $session,
            $this->server
        );
    }

    public function testDatabaseErrorThrowsException()
    {
        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willThrowException(new PDOException('DB connection failed'));

        // Mock DatabaseHelper to throw exception
        $dbHelperMock = $this->createStub(IDatabaseHelper::class);
        $dbHelperMock->method('getPDO')->willReturn($pdo);

        $handler = new BadgesHandler(
            $this->config,
            $dbHelperMock,
            $this->securityHelperMock,
            $this->loggerMock,
            $this->session,
            $this->server
        );

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Database error occurred');
        $this->expectExceptionCode(500);

        $handler->handleRequest();
    }

    public function testFetchBadgesQueryFailureThrowsException()
    {
        // Mock PDOStatement to throw exception on execute
        $stmtMock = $this->createStub(PDOStatement::class);
        $stmtMock->method('execute')->willReturn(false);

        // Mock PDO to return our statement mock
        $pdoMock = $this->createStub(PDO::class);
        $pdoMock->method('prepare')->willReturn($stmtMock);

        // Mock DatabaseHelper to return our PDO mock
        $dbHelperMock = $this->createStub(IDatabaseHelper::class);
        $dbHelperMock->method('getPDO')->willReturn($pdoMock);

        $handler = new BadgesHandler(
            $this->config,
            $dbHelperMock,
            $this->securityHelperMock,
            $this->loggerMock,
            $this->session,
            $this->server
        );

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Failed to fetch badges');
        $this->expectExceptionCode(500);

        $handler->handleRequest();
    }

    public function testNullStatsOrMissingTotalBadgesFieldThrowsException(): void {

        $databaseHelperMock = $this->createStub(IDatabaseHelper::class);
        $pdo = $this->createStub(PDO::class);
        $stmtMock = $this->createStub(PDOStatement::class);
        $stmtMock->method('execute')->willReturn(true);
        $stmtMock->method('fetch')->willReturn([/* 'total_badges' => 5 */]); // Missing total_badges field
        $pdo->method('prepare')->willReturn($stmtMock);
        $databaseHelperMock->method('getPDO')->willReturn($pdo);

        $handler = new BadgesHandler(
            $this->config,
            $databaseHelperMock,
            $this->securityHelperMock,
            $this->loggerMock,
            $this->session,
            $this->server
        );

        $reflection = new ReflectionClass(BadgesHandler::class);
        $method = $reflection->getMethod('fetchBadgeStats');

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Failed to fetch badge statistics');
        $this->expectExceptionCode(500);

        $method->invoke($handler);
    }

    // Tests requiring mock DB below

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testHandleRequestWithNoBadges()
    {
        $this->requireMockDB();

        $handler = $this->getHandler();

        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();

        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
        $this->assertEquals(0, $json['data']['stats']['total']);
        $this->assertEquals(0, $json['data']['stats']['earned']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testHandleRequestWithEarnedBadge()
    {
        $this->requireMockDB();

        // Insert a badge
        $this->pdo->exec("
            INSERT INTO badges (id, name, description, icon, rarity, requirements)
            VALUES (1, 'First Badge', 'Do something', 'icon.png', 'common', 'complete 1 challenge')
        ");

        // User has earned it
        $this->pdo->exec("
            INSERT INTO user_badges (user_id, badge_id, earned_at)
            VALUES (1, 1, '2025-01-01 00:00:00')
        ");

        $handler = $this->getHandler();

        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();

        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
        $this->assertCount(1, $json['data']['badges']);
        $this->assertEquals(1, $json['data']['stats']['earned']);
        $this->assertEquals(100, $json['data']['stats']['completion_rate']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testHandleRequestWithUnachievedBadge()
    {
        $this->requireMockDB();

        // Insert badge not yet earned
        $this->pdo->exec("
            INSERT INTO badges (id, name, description, icon, rarity, requirements)
            VALUES (2, 'Unachieved', 'Not yet', 'icon2.png', 'rare', 'earn 100 points')
        ");

        // Insert challenge + flag (user has only 10 points)
        $this->pdo->exec("INSERT INTO challenge_templates (id, category, difficulty, name) VALUES (1, 'web', 'easy', 'Sample Challenge')");
        $this->pdo->exec("INSERT INTO challenge_flags (id, challenge_template_id, points, flag) VALUES (1, 1, 10, 'FLAG{sample}')");
        $this->pdo->exec("INSERT INTO completed_challenges (user_id, challenge_template_id, flag_id) VALUES (1, 1, 1)");

        $handler = $this->getHandler();

        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();

        $json = json_decode($output, true);

        $this->assertTrue($json['success']);
        $this->assertCount(1, $json['data']['badges']);
        $this->assertFalse($json['data']['badges'][0]['earned']);
        $this->assertEquals(['current' => 10, 'max' => 100], $json['data']['badges'][0]['progress']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testSkipRowsWithInvalidBadgeFields()
    {
        $this->requireMockDB();

        $this->pdo->exec("
        INSERT INTO badges (id, name, description, icon, rarity, requirements)
            VALUES (1, 'Valid Badge', 'A valid badge', 'icon.png', 'common', 'requirement')
        ");
        $this->pdo->exec("
        INSERT INTO user_badges (user_id, badge_id, earned_at)
            VALUES (1, 1, '2025-01-01 00:00:00')
        ");

        $config = $this->config;
        $config['badge']['REQUIRED_FIELDS'][] = 'extra_field';

        $handler = new BadgesHandler(
            $config,
            $this->databaseHelper,
            $this->securityHelperMock,
            $this->loggerMock,
            $this->session,
            $this->server
        );

        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $this->assertEmpty($json['data']['badges']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testAllTypesOfRequirements(): void {
        $this->requireMockDB();

        $this->pdo->exec("
        INSERT INTO badges (id, name, description, icon, rarity, requirements)
            VALUES 
            (1, 'Challenge Badge', 'Earn by challenges', 'icon1.png', 'common', 'complete 5 challenge'),
            (2, 'Points Badge', 'Earn by points', 'icon2.png', 'rare', 'earn 50 points'),
            (3, 'Category Badge', 'Earn by category', 'icon3.png', 'epic', 'solve 3 web challenges'),
            (4, 'Multi Badge', 'Earn by multiple', 'icon4.png', 'legendary', 'earn all available badges')
        ");

        $this->pdo->exec("
        INSERT INTO challenge_templates (id, category, difficulty, name)
        VALUES (1, 'web', 'easy', 'Web Challenge 1'),
               (2, 'web', 'medium', 'Web Challenge 2'),
               (3, 'crypto', 'easy', 'Crypto Challenge 1')
        ");
        $this->pdo->exec("
        INSERT INTO challenge_flags (id, challenge_template_id, points, flag)
        VALUES (1, 1, 5, 'FLAG{1}'),
               (2, 2, 5, 'FLAG{2}'),
               (3, 3, 5, 'FLAG{3}')
        ");
        $this->pdo->exec("
        INSERT INTO completed_challenges (user_id, challenge_template_id, flag_id) VALUES
            (1, 1, 1),
            (1, 2, 2)
        ");

        $handler = $this->getHandler();
        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);

        $expectedProgress = [
            1 => ['current' => 2, 'max' => 5],  // Challenge Badge
            2 => ['current' => 10, 'max' => 50], // Points Badge
            3 => ['current' => 2, 'max' => 3],  // Category Badge
            4 => ['current' => 0, 'max' => 3],  // Multi Badge
        ];

        $expectedIDs = [1, 2, 3, 4];
        $foundIDs = [];
        foreach ($json['data']['badges'] as $badge)
            $foundIDs[] = $badge['id'];

        $this->assertEqualsCanonicalizing($expectedIDs, $foundIDs);

        foreach ($json['data']['badges'] as $badge)
            $this->assertEquals($expectedProgress[$badge['id']], $badge['progress']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testInvalidRequirementFormatReturnsNullProgress(): void
    {
        $this->requireMockDB();

        $this->pdo->exec("
        INSERT INTO badges (id, name, description, icon, rarity, requirements)
            VALUES (1, 'Bad Format', 'Invalid req', 'icon.png', 'common', 'invalid requirement format')
        ");

        $handler = $this->getHandler();

        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();
        $json = json_decode($output, true);
        $this->assertNull($json['data']['badges'][0]['progress']);
    }
}
