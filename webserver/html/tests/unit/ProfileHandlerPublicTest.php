<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\TestCase;

class ProfileHandlerPublicTest extends TestCase
{
    private PDO $pdo;

    private array $generalConfig;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;

    private ISession $session;
    private IServer $server;
    private IGet $get;

    private ISystem $system;

    private $mockDB;

    public function setUp(): void
    {
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->logger = new MockLogger();

        $this->session = new MockSession();
        $this->server = new MockServer();
        $this->get = new MockGet();

        $this->system = new SystemWrapper();

        $this->generalConfig = json_decode(file_get_contents(__DIR__ . '/../../config/general.config.json'), true);

        $this->mockDB = null;
    }

    private function requireMockDB(): void
    {
        $this->mockDB = new MockPostgresDB();
        $this->pdo = $this->mockDB->getPDO();
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);
    }

    private function setUpTestData(): array
    {
        $this->requireMockDB();

        $userId = 1;
        $username = 'admin';

        $userProfile = [
            'username' => $username,
            'user_id' => $userId,
            'full_name' => 'Test User',
            'bio' => 'This is a test user.',
            'github' => 'https://github.com/torvalds',
            'twitter' => 'https://x.com/Linus__Torvalds',
            'website' => 'https://www.kernel.org',
            'country' => 'US',
            'timezone' => 'America/New_York'
        ];

        $this->pdo->exec("
            INSERT INTO user_profiles (user_id, full_name, bio, github_url, twitter_url, website_url, country, timezone)
            VALUES (
                {$userProfile['user_id']},
                '{$userProfile['full_name']}',
                '{$userProfile['bio']}',
                '{$userProfile['github']}',
                '{$userProfile['twitter']}',
                '{$userProfile['website']}',
                '{$userProfile['country']}',
                '{$userProfile['timezone']}'
            );
        ");

        $userBadges = [];
        for ($id = 1; $id <= 9; $id++) {
            $hasBadge = random_int(0, 1);
            $userBadges[$id] = $hasBadge;
            if ($hasBadge)
                $this->pdo->exec("
                    INSERT INTO user_badges (user_id, badge_id, earned_at)
                    VALUES ($userId, $id, CURRENT_TIMESTAMP);
                ");
        }

        $config = require __DIR__ . '/../../config/backend.config.php';
        $validCategories = array_diff($config['filters']['CHALLENGE_CATEGORIES'], ['all']);
        $validDifficulties = array_diff($config['filters']['CHALLENGE_DIFFICULTIES'], ['all']);

        $numChallenges = 20;
        $userChallenges = [];
        for ($id = 1; $id <= $numChallenges; $id++) {
            $category = $validCategories[array_rand($validCategories)];
            $difficulty = $validDifficulties[array_rand($validDifficulties)];

            $flag1points = random_int(10, 100);
            $flag2points = random_int(10, 100);

            $numFlags = random_int(0, 2);

            $stmt = $this->pdo->prepare("
                INSERT INTO challenge_templates (name, category, difficulty, creator_id) 
                VALUES ('Challenge $id', '$category', '$difficulty', $userId) RETURNING id;
            ");
            $stmt->execute();
            $challengeId = $stmt->fetchColumn();

            $stmt = $this->pdo->prepare("
                INSERT INTO challenge_flags (challenge_template_id, flag, points)
                VALUES ($challengeId, 'FLAG{$id}1', $flag1points) RETURNING id;
            ");
            $stmt->execute();
            $flag1Id = $stmt->fetchColumn();

            $stmt = $this->pdo->prepare("
                INSERT INTO challenge_flags (challenge_template_id, flag, points)
                VALUES ($challengeId, 'FLAG{$id}2', $flag2points) RETURNING id;
            ");
            $stmt->execute();
            $flag2Id = $stmt->fetchColumn();

            if ($numFlags >= 1)
                $this->pdo->exec("
                    INSERT INTO completed_challenges (user_id, challenge_template_id, started_at, completed_at, flag_id) 
                    VALUES ($userId, $challengeId, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, $flag1Id);
                ");

            if ($numFlags == 2)
                $this->pdo->exec("
                    INSERT INTO completed_challenges (user_id, challenge_template_id, started_at, completed_at, flag_id)
                    VALUES ($userId, $challengeId, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, $flag2Id);
                ");

            $userChallenges[$id] = [
                'category' => $category,
                'difficulty' => $difficulty,
                'num_flags' => $numFlags,
                'flag_points' => [$flag1points, $flag2points]
            ];
        }

        return [
            'profile' => $userProfile,
            'badges' => $userBadges,
            'challenges' => $userChallenges
        ];
    }


    public function testInvalidSessionThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Unauthorized');
        $this->expectExceptionCode(401);

        new ProfileHandlerPublic(
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

    public function testEmptyRequestedUsernameThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = '';

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Username is required');
        $this->expectExceptionCode(400);

        new ProfileHandlerPublic(
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

    public function testTooLongRequestedUsernameThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = str_repeat('a', $this->generalConfig['user']['MAX_USERNAME_LENGTH'] + 1);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid username format');
        $this->expectExceptionCode(400);

        new ProfileHandlerPublic(
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

    public function testTooShortRequestedUsernameThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = str_repeat('a', $this->generalConfig['user']['MIN_USERNAME_LENGTH'] - 1);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid username format');
        $this->expectExceptionCode(400);

        new ProfileHandlerPublic(
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

    #[DataProvider('invalidUsernameProvider')] public function testInvalidCharactersInRequestedUsernameThrowsException(string $username): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = $username;

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid username format');
        $this->expectExceptionCode(400);

        new ProfileHandlerPublic(
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

    public static function invalidUsernameProvider(): array
    {
        $invalidChars = [' ', '!', '@', '#', '$', '%', '^', '&', '*', '(', ')', '+', '=', '{', '}', '[', ']', '|', '\\', ':', ';', '"', "'", '<', '>', ',', '.', '?', '/'];
        $data = [];
        foreach ($invalidChars as $char) {
            $data[] = ["valid{$char}name"];
        }
        return $data;
    }

    #[DataProvider('nonGetMethodsProvider')] public function testNonGetRequestsWithInvalidCsrfTokenThrowsException(string $method): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(false);

        $this->get = new MockGet();
        $this->get['username'] = 'validusername';

        $this->server = new MockServer();
        $this->server['REQUEST_METHOD'] = $method;

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid CSRF token');
        $this->expectExceptionCode(403);

        new ProfileHandlerPublic(
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

    public static function nonGetMethodsProvider(): array
    {
        return [
            ['POST'],
            ['PUT'],
            ['DELETE'],
            ['PATCH'],
        ];
    }

    public function testDatabaseErrorDuringUserFetchThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'validusername';

        $stmt = $this->createStub(PDOStatement::class);
        $stmt->method('execute')->willThrowException(new PDOException('Database error'));

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturn($stmt);

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Database error occurred');
        $this->expectExceptionCode(500);

        new ProfileHandlerPublic(
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

    public function testDatabaseErrorDuringBasicProfileDataFetchThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'validusername';

        $stmtUserIdFetch = $this->createStub(PDOStatement::class);
        $stmtUserIdFetch->method('execute')->willReturn(true);
        $stmtUserIdFetch->method('fetchColumn')->willReturn(1);

        $stmtBasicProfileFetch = $this->createStub(PDOStatement::class);
        $stmtBasicProfileFetch->method('execute')->willReturn(true);
        $stmtBasicProfileFetch->method('fetch')->willThrowException(new PDOException('Database error'));

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturnOnConsecutiveCalls(
            $stmtUserIdFetch,
            $stmtBasicProfileFetch
        );

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        ob_start();
        $handler = new ProfileHandlerPublic(
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
        $output = ob_get_clean();
        $response = json_decode($output, true);

        $this->assertFalse($response['success']);
        $this->assertEquals('An internal server error occurred', $response['message']);
    }

    public function testDatabaseNoDataDuringBasicProfileDataFetchThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'validusername';

        $stmtUserIdFetch = $this->createStub(PDOStatement::class);
        $stmtUserIdFetch->method('execute')->willReturn(true);
        $stmtUserIdFetch->method('fetchColumn')->willReturn(1);

        $stmtBasicProfileFetch = $this->createStub(PDOStatement::class);
        $stmtBasicProfileFetch->method('execute')->willReturn(true);
        $stmtBasicProfileFetch->method('fetch')->willReturn(false);

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturnOnConsecutiveCalls(
            $stmtUserIdFetch,
            $stmtBasicProfileFetch
        );

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        ob_start();
        $handler = new ProfileHandlerPublic(
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
        $output = ob_get_clean();
        $response = json_decode($output, true);

        $this->assertFalse($response['success']);
        $this->assertEquals('Profile data not found', $response['message']);
    }

    public function testDatabaseErrorDuringProfileStatsFetchThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'validusername';

        $stmtUserIdFetch = $this->createStub(PDOStatement::class);
        $stmtUserIdFetch->method('execute')->willReturn(true);
        $stmtUserIdFetch->method('fetchColumn')->willReturn(1);

        $stmtBasicProfileFetch = $this->createStub(PDOStatement::class);
        $stmtBasicProfileFetch->method('execute')->willReturn(true);
        $stmtBasicProfileFetch->method('fetch')->willReturn([
            'username' => 'validusername',
            'created_at' => '2026-01-01 00:00:00',
            'total_points' => 500,
            'solved_count' => 5,
            'full_name' => 'Test User',
            'bio' => 'This is a test user.',
            'github_url' => 'https://github.com/torvalds',
            'twitter_url' => 'https://x.com/Linus__Torvalds',
            'website_url' => 'https://www.kernel.org',
            'country' => 'US',
            'timezone' => 'America/New_York'
        ]);

        $stmtRankFetch = $this->createStub(PDOStatement::class);
        $stmtRankFetch->method('execute')->willReturn(true);
        $stmtRankFetch->method('fetch')->willReturn(['user_rank' => 1]);

        $stmtStatsFetch = $this->createStub(PDOStatement::class);
        $stmtStatsFetch->method('execute')->willThrowException(new PDOException('Database error'));

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturnOnConsecutiveCalls(
            $stmtUserIdFetch,
            $stmtBasicProfileFetch,
            $stmtRankFetch,
            $stmtStatsFetch
        );

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        ob_start();
        $handler = new ProfileHandlerPublic(
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
        $output = ob_get_clean();
        $response = json_decode($output, true);

        $this->assertFalse($response['success']);
        $this->assertEquals('An internal server error occurred', $response['message']);
    }

    public function testNoDataDuringProfileStatsFetchThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'validusername';

        $stmtUserIdFetch = $this->createStub(PDOStatement::class);
        $stmtUserIdFetch->method('execute')->willReturn(true);
        $stmtUserIdFetch->method('fetchColumn')->willReturn(1);

        $stmtBasicProfileFetch = $this->createStub(PDOStatement::class);
        $stmtBasicProfileFetch->method('execute')->willReturn(true);
        $stmtBasicProfileFetch->method('fetch')->willReturn([
            'username' => 'validusername',
            'created_at' => '2026-01-01 00:00:00',
            'total_points' => 500,
            'solved_count' => 5,
            'full_name' => 'Test User',
            'bio' => 'This is a test user.',
            'github_url' => 'https://github.com/torvalds',
            'twitter_url' => 'https://x.com/Linus__Torvalds',
            'website_url' => 'https://www.kernel.org',
            'country' => 'US',
            'timezone' => 'America/New_York'
        ]);

        $stmtRankFetch = $this->createStub(PDOStatement::class);
        $stmtRankFetch->method('execute')->willReturn(true);
        $stmtRankFetch->method('fetch')->willReturn(['user_rank' => 1]);

        $stmtStatsFetch = $this->createStub(PDOStatement::class);
        $stmtStatsFetch->method('execute')->willReturn(true);
        $stmtStatsFetch->method('fetch')->willReturn(false);

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturnOnConsecutiveCalls(
            $stmtUserIdFetch,
            $stmtBasicProfileFetch,
            $stmtRankFetch,
            $stmtStatsFetch
        );

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        ob_start();
        $handler = new ProfileHandlerPublic(
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
        $output = ob_get_clean();
        $response = json_decode($output, true);

        $this->assertFalse($response['success']);
        $this->assertEquals('An internal server error occurred', $response['message']);
    }

    public function testDatabaseErrorDuringCategoryDataFetchThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'validusername';

        $stmtUserIdFetch = $this->createStub(PDOStatement::class);
        $stmtUserIdFetch->method('execute')->willReturn(true);
        $stmtUserIdFetch->method('fetchColumn')->willReturn(1);

        $stmtBasicProfileFetch = $this->createStub(PDOStatement::class);
        $stmtBasicProfileFetch->method('execute')->willReturn(true);
        $stmtBasicProfileFetch->method('fetch')->willReturn([
            'username' => 'validusername',
            'created_at' => '2026-01-01 00:00:00',
            'total_points' => 500,
            'solved_count' => 5,
            'full_name' => 'Test User',
            'bio' => 'This is a test user.',
            'github_url' => 'https://github.com/torvalds',
            'twitter_url' => 'https://x.com/Linus__Torvalds',
            'website_url' => 'https://www.kernel.org',
            'country' => 'US',
            'timezone' => 'America/New_York'
        ]);

        $stmtRankFetch = $this->createStub(PDOStatement::class);
        $stmtRankFetch->method('execute')->willReturn(true);
        $stmtRankFetch->method('fetch')->willReturn(['user_rank' => 1]);

        $stmtStatsFetch = $this->createStub(PDOStatement::class);
        $stmtStatsFetch->method('execute')->willReturn(true);
        $stmtStatsFetch->method('fetch')->willReturn([
            'solved' => 5,
            'attempts' => 10,
            'total_points' => 500,
            'success_rate' => 50,
            'solved_web' => 2,
            'solved_crypto' => 1,
            'solved_forensics' => 1,
            'solved_reverse' => 0,
            'solved_pwn' => 1,
            'solved_misc' => 0
        ]);

        $stmtCategoryFetch = $this->createStub(PDOStatement::class);
        $stmtCategoryFetch->method('fetchAll')->willReturn([
            'web',
            'crypto',
            'forensics',
            'reverse',
            'pwn',
            'misc'
        ]);

        $stmtChallengeCategoryCount = $this->createStub(PDOStatement::class);
        $stmtChallengeCategoryCount->method('fetch')->willReturnOnConsecutiveCalls(
            ['category' => 'web', 'total' => 10],
            ['category' => 'crypto', 'total' => 8],
            ['category' => 'forensics', 'total' => 6],
            ['category' => 'reverse', 'total' => 4],
            ['category' => 'pwn', 'total' => 2],
            ['category' => 'misc', 'total' => 1],
            false
        );

        $stmtSolvedChallengesFetch = $this->createStub(PDOStatement::class);
        $stmtSolvedChallengesFetch->method('fetchAll')->willThrowException(new PDOException());

        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturnOnConsecutiveCalls(
            $stmtUserIdFetch,
            $stmtBasicProfileFetch,
            $stmtRankFetch,
            $stmtStatsFetch,
            $stmtSolvedChallengesFetch
        );
        $pdo->method('query')->willReturnOnConsecutiveCalls(
            $stmtCategoryFetch,
            $stmtChallengeCategoryCount
        );

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        ob_start();
        $handler = new ProfileHandlerPublic(
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
        $output = ob_get_clean();
        $response = json_decode($output, true);

        $this->assertFalse($response['success']);
        $this->assertEquals('An internal server error occurred', $response['message']);
    }

    public function testDatabaseErrorDuringBadgesFetchThrowsException(): void
    {
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'validusername';

        $stmtUserIdFetch = $this->createStub(PDOStatement::class);
        $stmtUserIdFetch->method('execute')->willReturn(true);
        $stmtUserIdFetch->method('fetchColumn')->willReturn(1);

        $stmtBasicProfileFetch = $this->createStub(PDOStatement::class);
        $stmtBasicProfileFetch->method('execute')->willReturn(true);
        $stmtBasicProfileFetch->method('fetch')->willReturn([
            'username' => 'validusername',
            'created_at' => '2026-01-01 00:00:00',
            'total_points' => 500,
            'solved_count' => 5,
            'full_name' => 'Test User',
            'bio' => 'This is a test user.',
            'github_url' => 'https://github.com/torvalds',
            'twitter_url' => 'https://x.com/Linus__Torvalds',
            'website_url' => 'https://www.kernel.org',
            'country' => 'US',
            'timezone' => 'America/New_York'
        ]);

        $stmtRankFetch = $this->createStub(PDOStatement::class);
        $stmtRankFetch->method('execute')->willReturn(true);
        $stmtRankFetch->method('fetch')->willReturn(['user_rank' => 1]);

        $stmtStatsFetch = $this->createStub(PDOStatement::class);
        $stmtStatsFetch->method('execute')->willReturn(true);
        $stmtStatsFetch->method('fetch')->willReturn([
            'solved' => 5,
            'attempts' => 10,
            'total_points' => 500,
            'success_rate' => 50,
            'solved_web' => 2,
            'solved_crypto' => 1,
            'solved_forensics' => 1,
            'solved_reverse' => 0,
            'solved_pwn' => 1,
            'solved_misc' => 0
        ]);

        $stmtCategoryFetch = $this->createStub(PDOStatement::class);
        $stmtCategoryFetch->method('fetchAll')->willReturn([
            'web',
            'crypto',
            'forensics',
            'reverse',
            'pwn',
            'misc'
        ]);

        $stmtChallengeCategoryCount = $this->createStub(PDOStatement::class);
        $stmtChallengeCategoryCount->method('fetch')->willReturnOnConsecutiveCalls(
            ['category' => 'web', 'total' => 10],
            ['category' => 'crypto', 'total' => 8],
            ['category' => 'forensics', 'total' => 6],
            ['category' => 'reverse', 'total' => 4],
            ['category' => 'pwn', 'total' => 2],
            ['category' => 'misc', 'total' => 1],
            false
        );

        $stmtSolvedChallengesFetch = $this->createStub(PDOStatement::class);
        $stmtSolvedChallengesFetch->method('fetchAll')->willReturn([
            ['challenge_template_id' => 1],
            ['challenge_template_id' => 2],
            ['challenge_template_id' => 3]
        ]);

        $stmtBadgesFetch = $this->createStub(PDOStatement::class);
        $stmtBadgesFetch->method('execute')->willReturn(true);
        $stmtBadgesFetch->method('fetchAll')->willThrowException(new PDOException('Database error'));


        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willReturnOnConsecutiveCalls(
            $stmtUserIdFetch,
            $stmtBasicProfileFetch,
            $stmtRankFetch,
            $stmtStatsFetch,
            $stmtSolvedChallengesFetch,
            $stmtBadgesFetch
        );
        $pdo->method('query')->willReturnOnConsecutiveCalls(
            $stmtCategoryFetch,
            $stmtChallengeCategoryCount
        );

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        ob_start();
        $handler = new ProfileHandlerPublic(
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
        $output = ob_get_clean();
        $response = json_decode($output, true);

        $this->assertFalse($response['success']);
        $this->assertEquals('An internal server error occurred', $response['message']);
    }



    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testNoChallengeCategoriesThrowsException(): void
    {
        $this->requireMockDB();

        $this->pdo->exec("
            DROP TYPE IF EXISTS challenge_category CASCADE;
            CREATE TYPE challenge_category AS ENUM ();
        ");

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'admin';
        $this->get['user_id'] = 1;

        ob_start();
        $handler = new ProfileHandlerPublic(
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
        $output = ob_get_clean();
        $response = json_decode($output, true);

        $this->assertFalse($response['success']);
        $this->assertEquals('An internal server error occurred', $response['message']);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testNonExistentUserThrowsException(): void
    {
        $this->requireMockDB();

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'nonexistentuser';
        $this->get['user_id'] = 9999;

        $this->expectException(CustomException::class);
        $this->expectExceptionMessage('Profile not found');
        $this->expectExceptionCode(404);

        new ProfileHandlerPublic(
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
    public function testSuccessfulRequestHandling(): void
    {
        $insertedData = $this->setUpTestData();
        $profileData = $insertedData['profile'];
        $badgesData = $insertedData['badges'];
        $challengesData = $insertedData['challenges'];

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper->method('validateSession')->willReturn(true);

        $this->get = new MockGet();
        $this->get['username'] = 'admin';

        $this->session['user_id'] = 1;
        $this->session['authenticated'] = true;

        ob_start();
        $handler = new ProfileHandlerPublic(
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
        $output = ob_get_clean();
        $response = json_decode($output, true);
        $this->assertTrue($response['success']);

        $data = $response['data'];

        $totalExpectedPoints = 0;
        $totalExpectedSolved = 0;
        foreach ($challengesData as $challenge) {
            $totalExpectedSolved += ($challenge['num_flags'] == 2) ? 1 : 0;
            $totalExpectedPoints += match($challenge['num_flags']) {
                1 => $challenge['flag_points'][0],
                2 => $challenge['flag_points'][0] + $challenge['flag_points'][1],
                default => 0,
            };
        }

        $receivedProfileData = $data['profile'];
        $this->assertEquals($profileData['username'], $receivedProfileData['username']);
        $this->assertEquals($profileData['full_name'], $receivedProfileData['full_name']);
        $this->assertEquals($profileData['bio'], $receivedProfileData['bio']);
        $this->assertEquals($profileData['github'], $receivedProfileData['social_links']['github']);
        $this->assertEquals($profileData['twitter'], $receivedProfileData['social_links']['twitter']);
        $this->assertEquals($profileData['website'], $receivedProfileData['social_links']['website']);
        $this->assertEquals($totalExpectedPoints, $receivedProfileData['points']);
        $this->assertEquals($totalExpectedSolved, $receivedProfileData['solved_count']);


        $receivedStatsData = $data['stats'];
        $solvedCounts = [];
        $successes = 0;
        $attempts = 0;
        foreach ($challengesData as $challenge) {
            $category = $challenge['category'];
            if (!isset($solvedCounts[$category]))
                $solvedCounts[$category] = 0;
            if ($challenge['num_flags'] == 2) {
                $solvedCounts[$category]++;
                $successes++;
            }
            if ($challenge['num_flags'] > 0)
                $attempts++;
        }

        foreach ($receivedStatsData['solved_counts'] as $category => $count)
            $this->assertEquals($solvedCounts[$category] ?? 0, $count);

        $successRate = (int)round(($attempts > 0 ? ($successes / $attempts) * 100 : 0));
        $this->assertEquals($successRate, $receivedStatsData['success_rate']);
        $this->assertEquals($successes, $receivedStatsData['total_solved']);
        $this->assertEquals($attempts, $receivedStatsData['total_attempts']);
        $this->assertEquals($totalExpectedPoints, $receivedStatsData['total_points']);


        $receivedBadgesData = $data['badges'];
        $receivedEarnedBadgeIds = array_map(fn($b) => $b['id'], $receivedBadgesData['badges']);
        $expectedEarnedBadgeIds = [];
        foreach ($badgesData as $badgeId => $hasBadge)
            if ($hasBadge)
                $expectedEarnedBadgeIds[] = $badgeId;

        $this->assertEquals(count($badgesData), $receivedBadgesData['total_badges']);
        $this->assertEquals(count($expectedEarnedBadgeIds), $receivedBadgesData['earned_count']);
        $this->assertEqualsCanonicalizing($expectedEarnedBadgeIds, $receivedEarnedBadgeIds);
    }
}

