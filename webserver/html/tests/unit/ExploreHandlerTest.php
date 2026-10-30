<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\TestCase;

class ExploreHandlerTest extends TestCase
{
    private PDO $pdo;
    private array $generalConfig;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;
    private IAuthHelper $authHelper;
    private ICurlHelper $curlHelper;

    private ISession $session;
    private IServer $server;
    private IGet $get;

    private ISystem $system;

    private $mockDB;

    private array $categories;
    private array $difficulties;
    private array $sortOptions;

    public function setUp(): void {
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->logger = new MockLogger();

        $this->session = new MockSession();
        $this->server = new MockServer();
        $this->get = new MockGet();

        $this->system = new SystemWrapper();

        $this->generalConfig = require __DIR__ . '/../../config/backend.config.php';

        // Mock PDO for database interactions
        $this->mockDB = null;

        $this->categories = $this->generalConfig['filters']['CHALLENGE_CATEGORIES'];
        $this->difficulties = $this->generalConfig['filters']['CHALLENGE_DIFFICULTIES'];
        $this->sortOptions = $this->generalConfig['sorts']['VALID'];
    }

    private function setupMockDatabase(): array {
        $this->mockDB = new MockPostgresDB();
        $this->pdo = $this->mockDB->getPDO();
        $this->databaseHelper = $this->createStub(DatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);

        $combinations = (count($this->categories) - 1) * (count($this->difficulties) - 1);

        $availableAttempts = range(1, $combinations + 1);
        $availableDaysAgo = range(1, $combinations + 1);

        $idToAttributeMapping = [];

        foreach ($this->categories as $category) {
            foreach ($this->difficulties as $difficulty) {
                if ($category === "all")
                    continue;
                elseif ($difficulty === "all")
                    continue;

                $daysUploadedAgo = array_rand($availableDaysAgo);
                $availableDaysAgo = array_diff($availableDaysAgo, [$daysUploadedAgo]);

                $name = "challenge-$category-$difficulty";
                $stmt = $this->pdo->prepare("
                INSERT INTO challenge_templates (name, category, difficulty, created_at, creator_id, description, is_active)
                VALUES ('$name', '$category', '$difficulty', TO_TIMESTAMP('2000-01-01 00:00:00', 'YYYY-MM-DD HH24:MI:SS') - INTERVAL '$daysUploadedAgo days', 1, 'Description for $name', true)
                RETURNING id;
                ");
                $stmt->execute();
                $id = $stmt->fetchColumn();

                $stmt = $this->pdo->prepare("
                    INSERT INTO challenge_flags (challenge_template_id, flag, points)
                    VALUES ($id, 'FLAG{$id}A', 10) 
                    RETURNING id;
                ");
                $stmt->execute();
                $flag1ID = $stmt->fetchColumn();

                $stmt = $this->pdo->prepare("
                    INSERT INTO challenge_flags (challenge_template_id, flag, points) 
                    VALUES ($id, 'FLAG{$id}B', 20) 
                    RETURNING id;
                ");
                $stmt->execute();
                $flag2ID = $stmt->fetchColumn();

                $attempts = array_rand($availableAttempts);
                $availableAttempts = array_diff($availableAttempts, [$attempts]);
                $solves = rand(0, $attempts);

                for ($i = 0; $i < $attempts; $i++) {
                    $stmt = $this->pdo->prepare("
                        INSERT INTO users (username, email, password_hash, password_salt)
                        VALUES ('user_{$id}_$i', 'test_{$id}_$i@test.test', 'some_irrelevant_hash', 'some_irrelevant_salt')
                        RETURNING id;
                    ");
                    $stmt->execute();
                    $userId = $stmt->fetchColumn();

                    $stmt = $this->pdo->prepare("
                        INSERT INTO completed_challenges (user_id, challenge_template_id, completed_at, flag_id)
                        VALUES ($userId, $id, CURRENT_TIMESTAMP, $flag1ID);
                    ");
                    $stmt->execute();
                    
                    if($i < $solves) {
                        $stmt = $this->pdo->prepare("
                            INSERT INTO completed_challenges (user_id, challenge_template_id, completed_at, flag_id)
                            VALUES ($userId, $id, CURRENT_TIMESTAMP, $flag2ID);
                        ");
                        $stmt->execute();
                    }
                }

                $idToAttributeMapping[$id] = [
                    'name' => $name,
                    'category' => $category,
                    'difficulty' => $difficulty,
                    'days_uploaded_ago' => $daysUploadedAgo,
                    'attempts' => $attempts,
                    'solves' => $solves
                ];
            }
        }

        return $idToAttributeMapping;
    }

    private function setupSolvingUser(array &$idToAttributeMapping): array
    {
        $stmt = $this->pdo->prepare("
            INSERT INTO users (username, email, password_hash, password_salt)
            VALUES ('solving_user', 'solving_user@test.test', 'some_irrelevant_hash', 'some_irrelevant_salt')
            RETURNING id;
        ");
        $stmt->execute();
        $userId = $stmt->fetchColumn();

        $data = [
            'id' => $userId,
            'username' => 'solving_user',
            'flags' => []
        ];

        $flags = 2;

        foreach ($idToAttributeMapping as $challengeId => &$attributes) {
            $flags = ($flags + 1) % 3;
            $data['flags'][$challengeId] = $flags;

            if ($flags === 0)
                continue;

            $stmt = $this->pdo->prepare("
                SELECT id FROM challenge_flags 
                WHERE challenge_template_id = $challengeId 
                ORDER BY points ASC 
                LIMIT 1;
            ");
            $stmt->execute();
            $flagId1 = $stmt->fetchColumn();

            $stmt = $this->pdo->prepare("
                SELECT id FROM challenge_flags 
                WHERE challenge_template_id = $challengeId 
                ORDER BY points DESC 
                LIMIT 1;
            ");
            $stmt->execute();
            $flagId2 = $stmt->fetchColumn();

            $stmt = $this->pdo->prepare("
                INSERT INTO completed_challenges (user_id, challenge_template_id, completed_at, flag_id)
                VALUES ($userId, $challengeId, CURRENT_TIMESTAMP, $flagId1);
            ");
            $stmt->execute();

            $attributes['attempts'] += 1;

            if($flags === 2) {
                $attributes['solves'] += 1;
                $stmt = $this->pdo->prepare("
                    INSERT INTO completed_challenges (user_id, challenge_template_id, completed_at, flag_id)
                    VALUES ($userId, $challengeId, CURRENT_TIMESTAMP, $flagId2);
                ");
                $stmt->execute();
            }
        }

        return $data;
    }

    public function testDatabaseErrorThrowsException(): void {
        $pdo = $this->createStub(PDO::class);
        $pdo->method('prepare')->willThrowException(new PDOException("Database error"));
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($pdo);

        $handler = new ExploreHandler(
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
        $this->expectExceptionMessage("Failed to retrieve challenges");
        $this->expectExceptionCode(500);

        $handler->handleRequest();
    }

    public function testFetchErrorOnFetchDuringUserChallengeDataRetrievalReturnNullSolveStatus(): void {
        $this->session['user_id'] = 3;
        $this->session['username'] = 'testuser';


        $countStmt = $this->createStub(PDOStatement::class);
        $countStmt->method('execute')->willReturn(true);
        $countStmt->method('fetchColumn')->willReturn(1);

        $fetchStmt = $this->createStub(PDOStatement::class);
        $fetchStmt->method('execute')->willReturn(true);
        $fetchStmt->method('fetchAll')->willReturn([
            [
                'id' => 1,
                'name' => 'challenge-1',
                'created_at' => '2026-01-01 00:00:00',
                'is_active' => true,
                'description' => 'A test challenge',
                'category' => 'web',
                'difficulty' => 'easy',
                'attempts' => 10,
                'solves' => 5,
                'days_uploaded_ago' => 30
            ]
        ]);

        $userStmt = $this->createStub(PDOStatement::class);
        $userStmt->method('execute')->willReturn(true);
        $userStmt->method('fetchColumn')->willThrowException(new PDOException("Database error"));

        $mockPDO = $this->createStub(PDO::class);
        $mockPDO->method('prepare')->willReturnOnConsecutiveCalls(
            $countStmt,
            $fetchStmt,
            $userStmt
        );

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($mockPDO);

        ob_start();
        $handler = new ExploreHandler(
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
        $jsonOutput = json_decode($output, true);

        $this->assertTrue($jsonOutput['success']);
        $this->assertArrayHasKey('data', $jsonOutput);
        $this->assertCount(1, $jsonOutput['data']['challenges']);
        $this->assertNull($jsonOutput['data']['challenges'][0]['solved']);
    }

    public function testFetchPDOErrorOnFetchDuringUserChallengeDataRetrievalReturnNullSolveStatus(): void {
        $this->session['user_id'] = 3;
        $this->session['username'] = 'testuser';


        $countStmt = $this->createStub(PDOStatement::class);
        $countStmt->method('execute')->willReturn(true);
        $countStmt->method('fetchColumn')->willReturn(1);

        $fetchStmt = $this->createStub(PDOStatement::class);
        $fetchStmt->method('execute')->willReturn(true);
        $fetchStmt->method('fetchAll')->willReturn([
            [
                'id' => 1,
                'name' => 'challenge-1',
                'created_at' => '2026-01-01 00:00:00',
                'is_active' => true,
                'description' => 'A test challenge',
                'category' => 'web',
                'difficulty' => 'easy',
                'attempts' => 10,
                'solves' => 5,
                'days_uploaded_ago' => 30
            ]
        ]);

        $userStmt = $this->createStub(PDOStatement::class);
        $userStmt->method('execute')->willReturn(true);
        $userStmt->method('fetch')->willThrowException(new PDOException()); // Simulate error

        $mockPDO = $this->createStub(PDO::class);
        $mockPDO->method('prepare')->willReturnOnConsecutiveCalls(
            $countStmt,
            $fetchStmt,
            $userStmt
        );

        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($mockPDO);

        ob_start();
        $handler = new ExploreHandler(
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
        $jsonOutput = json_decode($output, true);

        $this->assertTrue($jsonOutput['success']);
        $this->assertArrayHasKey('data', $jsonOutput);
        $this->assertCount(1, $jsonOutput['data']['challenges']);
        $this->assertNull($jsonOutput['data']['challenges'][0]['solved']);
    }

    // Tests requiring the mock database to be set up

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testInvalidFilterAndSortParametersDefaultCorrectly(): void {
        $insertedChallenges = $this->setupMockDatabase();

        $this->get['category'] = 'invalid-category';
        $this->get['difficulty'] = 'invalid-difficulty';
        $this->get['sort'] = 'invalid-sort';

        $receivedIDs = [];

        $page = 1;

        do {
            $this->get['page'] = (string)($page == 1 ? -1 : $page); // First request with -1 to test wrong page handling
            $page++;

            ob_start();
            $handler = new ExploreHandler(
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
            $jsonOutput = json_decode($output, true);

            $this->assertTrue($jsonOutput['success']);
            $this->assertArrayHasKey('data', $jsonOutput);
            $this->assertEmpty($jsonOutput['data']['filters']['search']);
            $this->assertEquals('all', $jsonOutput['data']['filters']['category']);
            $this->assertEquals('all', $jsonOutput['data']['filters']['difficulty']);
            $this->assertEquals('popularity', $jsonOutput['data']['filters']['sort']);

            $receivedIDs = array_merge($receivedIDs, array_column($jsonOutput['data']['challenges'], 'id'));
            $totalPages = $jsonOutput['data']['pagination']['total_pages'];
        } while ($page <= $totalPages);

        $expectedIDs = array_keys($insertedChallenges);
        $this->assertEqualsCanonicalizing($expectedIDs, $receivedIDs);
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testSearchAsFilter(): void
    {
        $insertedChallenges = $this->setupMockDatabase();

        foreach (array_merge($this->categories, $this->difficulties) as $searchTerm) {
            if ($searchTerm === 'all')
                continue;
            foreach ($this->sortOptions as $sort) {
                $this->get['search'] = $searchTerm;
                $this->get['sort'] = $sort;

                $category = in_array($searchTerm, $this->categories) ? $searchTerm : 'all';
                $difficulty = in_array($searchTerm, $this->difficulties) ? $searchTerm : 'all';

                $receivedIDs = [];

                $page = 1;

                do {
                    $this->get['page'] = (string)$page;
                    $page++;

                    ob_start();
                    $handler = new ExploreHandler(
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
                    $jsonOutput = json_decode($output, true);

                    $this->assertTrue($jsonOutput['success']);
                    $this->assertArrayHasKey('data', $jsonOutput);
                    $this->assertStringContainsString($searchTerm, $jsonOutput['data']['filters']['search']);
                    $this->assertEquals('all', $jsonOutput['data']['filters']['category']);
                    $this->assertEquals('all', $jsonOutput['data']['filters']['difficulty']);
                    $this->assertEquals($sort, $jsonOutput['data']['filters']['sort']);

                    $receivedIDs = array_merge($receivedIDs, array_column($jsonOutput['data']['challenges'], 'id'));
                    $totalPages = $jsonOutput['data']['pagination']['total_pages'];
                } while ($page <= $totalPages);

                $expectedIDs = array_filter(array_keys($insertedChallenges),
                    function ($id) use ($insertedChallenges, $category, $difficulty, $sort) {
                        $challenge = $insertedChallenges[$id];
                        if ($category !== 'all' && $challenge['category'] !== $category) {
                            return false;
                        }
                        if ($difficulty !== 'all' && $challenge['difficulty'] !== $difficulty) {
                            return false;
                        }
                        return true;
                    }
                );

                usort($expectedIDs, function ($a, $b) use ($insertedChallenges, $sort) {
                    if ($sort === 'popularity') {
                        return $insertedChallenges[$b]['solves'] <=> $insertedChallenges[$a]['solves'] ?:
                            $insertedChallenges[$b]['attempts'] <=> $insertedChallenges[$a]['attempts'] ?:
                                $a <=> $b;
                    } elseif ($sort === 'date') {
                        return $insertedChallenges[$a]['days_uploaded_ago'] <=> $insertedChallenges[$b]['days_uploaded_ago'] ?:
                            $a <=> $b;
                    } elseif ($sort === 'difficulty') {
                        $d1 = $insertedChallenges[$a]['difficulty'];
                        $d2 = $insertedChallenges[$b]['difficulty'];
                        $difficultyOrder = ['easy' => 1, 'medium' => 2, 'hard' => 3];
                        return $difficultyOrder[$d1] <=> $difficultyOrder[$d2] ?:
                            $a <=> $b;
                    }
                    return 0;
                });

                $this->assertEqualsCanonicalizing($expectedIDs, $receivedIDs);
            }
        }
    }

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testValidFilterAndSortParametersWorkAndSolvingUserGetsSolvingInfoCorrectly(): void
    {
        $insertedChallenges = $this->setupMockDatabase();
        $userData = $this->setupSolvingUser($insertedChallenges);

        $this->session['user_id'] = $userData['id'];
        $this->session['username'] = $userData['username'];

        foreach ($this->categories as $category) {
            foreach ($this->difficulties as $difficulty) {
                foreach ($this->sortOptions as $sort) {
                    $this->get['category'] = $category;
                    $this->get['difficulty'] = $difficulty;
                    $this->get['sort'] = $sort;

                    $receivedIDs = [];

                    $page = 1;

                    do {
                        $this->get['page'] = (string)$page;
                        $page++;

                        ob_start();
                        $handler = new ExploreHandler(
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
                        $jsonOutput = json_decode($output, true);

                        $this->assertTrue($jsonOutput['success']);
                        $this->assertArrayHasKey('data', $jsonOutput);
                        $this->assertEmpty($jsonOutput['data']['filters']['search']);
                        $this->assertEquals($category, $jsonOutput['data']['filters']['category']);
                        $this->assertEquals($difficulty, $jsonOutput['data']['filters']['difficulty']);
                        $this->assertEquals($sort, $jsonOutput['data']['filters']['sort']);

                        foreach ($jsonOutput['data']['challenges'] as $challenge) {
                            $id = $challenge['id'];
                            $expectedSolveStatus = $userData['flags'][$id] === null ? null : $userData['flags'][$id] === 2;
                            $this->assertEquals($expectedSolveStatus, $challenge['solved']);
                        }

                        foreach ($jsonOutput['data']['challenges'] as $challenge) {
                            if ($category !== 'all')
                                $this->assertEquals($category, $challenge['category']);
                            if ($difficulty !== 'all')
                                $this->assertEquals($difficulty, $challenge['difficulty']);
                        }

                        $receivedIDs = array_merge($receivedIDs, array_column($jsonOutput['data']['challenges'], 'id'));
                        $totalPages = $jsonOutput['data']['pagination']['total_pages'];
                    } while ($page <= $totalPages);

                    $expectedIDs = array_filter(array_keys($insertedChallenges),
                        function ($id) use ($insertedChallenges, $category, $difficulty, $sort) {
                            $challenge = $insertedChallenges[$id];
                            if ($category !== 'all' && $challenge['category'] !== $category) {
                                return false;
                            }
                            if ($difficulty !== 'all' && $challenge['difficulty'] !== $difficulty) {
                                return false;
                            }
                            return true;
                        }
                    );

                    usort($expectedIDs, function ($a, $b) use ($insertedChallenges, $sort) {
                        if ($sort === 'popularity') {
                            return $insertedChallenges[$b]['solves'] <=> $insertedChallenges[$a]['solves'] ?:
                                $insertedChallenges[$b]['attempts'] <=> $insertedChallenges[$a]['attempts'] ?:
                                    $a <=> $b;
                        } elseif ($sort === 'date') {
                            return $insertedChallenges[$a]['days_uploaded_ago'] <=> $insertedChallenges[$b]['days_uploaded_ago'] ?:
                                $a <=> $b;
                        } elseif ($sort === 'difficulty') {
                            $d1 = $insertedChallenges[$a]['difficulty'];
                            $d2 = $insertedChallenges[$b]['difficulty'];
                            $difficultyOrder = ['easy' => 1, 'medium' => 2, 'hard' => 3];
                            return $difficultyOrder[$d1] <=> $difficultyOrder[$d2] ?:
                                $a <=> $b;
                        }
                        return 0;
                    });

                    $this->assertEqualsCanonicalizing($expectedIDs, $receivedIDs);
                }
            }
        }
    }
}

