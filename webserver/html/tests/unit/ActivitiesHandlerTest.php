<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\TestCase;

class ActivitiesHandlerTest extends TestCase
{
    private PDO $pdo;
    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;
    private ISession $session;
    private IServer $server;
    private IGet $get;
    private array $config;
    private array $activityTypes;
    private array $activityRanges;
    private array $challengeCategories;
    private ?int $userId;
    private $mockDB;

    protected function setUp(): void
    {
        $this->mockDB = null;
        $this->pdo = $this->createStub(PDO::class);
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->logger = new MockLogger();

        $this->session = new MockSession();
        $this->session['user_id'] = 1;
        $this->session['csrf_token'] = 'valid_token';

        $this->server = new MockServer();
        $this->server['REQUEST_METHOD'] = 'GET';
        $this->server['HTTP_USER_AGENT'] = 'TestAgent';
        $this->server['REMOTE_ADDR'] = '192.168.0.2';

        $this->get = new MockGet();
        $this->get['type'] = 'all';
        $this->get['range'] = 'all';
        $this->get['category'] = 'all';

        $this->config = require __DIR__ . "/../../config/backend.config.php";
        $this->activityTypes = $this->config['filters']['ACTIVITY_TYPES'];
        $this->activityTypes = array_merge($this->activityTypes, ['flag_submitted']);
        $this->activityRanges = $this->config['filters']['ACTIVITY_RANGES'];
        $this->challengeCategories = $this->config['filters']['CHALLENGE_CATEGORIES'];

        $this->userId = $this->session['user_id'] ?? 1;
    }

    private function requireMockDB(): void {
        $this->mockDB = new MockPostgresDB();
        $this->pdo = $this->mockDB->getPDO();
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);
    }

    private function makeDateForRange(string $range): string
    {
        return match ($range) {
            'today' => 'CURRENT_TIMESTAMP - INTERVAL \'2 hours\'',
            'week'  => 'CURRENT_TIMESTAMP - INTERVAL \'3 days\'',
            'month' => 'CURRENT_TIMESTAMP - INTERVAL \'15 days\'',
            'year'  => 'CURRENT_TIMESTAMP - INTERVAL \'6 months\'',
            'all'   => 'CURRENT_TIMESTAMP - INTERVAL \'5 years\'',
            default => throw new CustomException("Unknown range: $range"),
        };
    }


    private function combinationToId(string $type, string $range, string $category): int
    {
        if ($type === 'badges') {
            $ranges = array_values(array_filter($this->activityRanges, fn($r) => $r !== 'all'));
            $categories = array_values(array_filter($this->challengeCategories, fn($c) => $c === 'all'));

            $r = array_search($range, $ranges, true);
            $c = array_search($category, $categories, true);

            if ($r === false || $c === false) {
                throw new CustomException("Invalid badge filter value: [$range, $category]");
            }

            // Badge IDs start after challenge IDs offset
            $offset = count($this->getChallengeCombinations());
            return $offset + $r * count($categories) + $c + 1;
        } else {
            // Challenge types
            $types = array_values(array_filter($this->activityTypes, fn($t) => $t !== 'all' && $t !== 'badges'));
            $ranges = array_values(array_filter($this->activityRanges, fn($r) => $r !== 'all'));
            $categories = array_values(array_filter($this->challengeCategories, fn($c) => $c !== 'all'));

            $t = array_search($type, $types, true);
            $r = array_search($range, $ranges, true);
            $c = array_search($category, $categories, true);

            if ($t === false || $r === false || $c === false) {
                throw new CustomException("Invalid challenge filter value: [$type, $range, $category]");
            }

            return $t * count($ranges) * count($categories) + $r * count($categories) + $c + 1;
        }
    }

    /**
     * Helper to count total challenge combinations (excluding badges)
     */
    private function getChallengeCombinations(): array
    {
        $types = array_values(array_filter($this->activityTypes, fn($t) => $t !== 'all' && $t !== 'badges'));
        $ranges = array_values(array_filter($this->activityRanges, fn($r) => $r !== 'all'));
        $categories = array_values(array_filter($this->challengeCategories, fn($c) => $c !== 'all'));

        $combos = [];
        foreach ($types as $t) {
            foreach ($ranges as $r) {
                foreach ($categories as $c) {
                    $combos[] = [$t, $r, $c];
                }
            }
        }
        return $combos;
    }

    private function setupInMemoryDB(): void
    {
        $this->requireMockDB();

        $types = array_values(array_filter($this->activityTypes, fn($t) => $t !== 'all'));
        $ranges = array_values(array_filter($this->activityRanges, fn($r) => $r !== 'all'));
        $categories = array_values(array_filter($this->challengeCategories, fn($c) => $c !== 'all'));

        // --- Insert challenge activities ---
        foreach ($types as $type) {
            if ($type === 'badges') continue;
            foreach ($ranges as $range) {
                foreach ($categories as $category) {
                    $cid = $this->combinationToId($type, $range, $category);

                    $this->pdo->prepare("
                INSERT INTO challenge_templates (id, name, category, difficulty)
                VALUES (?, ?, ?, 'easy')
            ")->execute([$cid, "Challenge-$cid", $category]);

                    $this->pdo->prepare("
                INSERT INTO challenge_flags (id, challenge_template_id, points, flag)
                VALUES (?, ?, ?, 'FLAG{test_flag}')
            ")->execute([$cid, $cid, 100]);

                    $startedAt = $this->makeDateForRange($range);
                    $completedAt = "NULL";
                    $flagId = null;

                    if ($type === "solved") {
                        $completedAt = $this->makeDateForRange($range);
                        $flagId = $cid;
                    } elseif ($type === "failed") {
                        $completedAt = $this->makeDateForRange($range);
                    } elseif ($type === 'flag_submitted') {
                        $completedAt = $this->makeDateForRange($range);
                        $flagId = $cid; // Use the challenge ID as flag ID

                        $this->pdo->prepare("
                INSERT INTO challenge_flags (id, challenge_template_id, points, flag)
                VALUES (?, ?, ?, 'FLAG{test_flag2}')
            ")->execute([$flagId + 10000, $cid, 100]);
                    }

                    $this->pdo->prepare("
                INSERT INTO completed_challenges
                (id, challenge_template_id, user_id, flag_id, started_at, completed_at)
                VALUES (?, ?, ?, ?, $startedAt, $completedAt)
            ")->execute([$cid, $cid, $this->userId, $flagId]);
                }
            }
        }

        // --- Insert exactly one badge per combination ---
        foreach ($ranges as $range) {
            // Generate ID consistently for a single badge
            $cid = $this->combinationToId('badges', $range, 'all');

            $this->pdo->prepare("
                INSERT INTO badges (id, name, icon, color, rarity, description, requirements)
                VALUES (?, ?, 'icon.png', 'blue', 'common', 'test badge', 'requirement')
            ")->execute([$cid, "Badge-$cid"]);

            $earnedAt = $this->makeDateForRange($range);
            $this->pdo->prepare("
                INSERT INTO user_badges (badge_id, user_id, earned_at)
                VALUES (?, ?, $earnedAt)
            ")->execute([$cid, $this->userId]);
        }
    }



    private function makeHandler(): ActivitiesHandler
    {
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);

        $this->securityHelper->method('validateSession')->willReturn(true);
        $this->securityHelper->method('validateCsrfToken')->willReturn(true);

        return new ActivitiesHandler(
            config: $this->config,
            databaseHelper: $this->databaseHelper,
            securityHelper: $this->securityHelper,
            logger: $this->logger,
            session: $this->session,
            server: $this->server,
            get: $this->get
        );
    }

    public function testConstructorThrowsOnInvalidSession(): void
    {
        $this->securityHelper->method('validateSession')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Unauthorized');

        $this->makeHandler();
    }

    public function testConstructorThrowsOnInvalidCsrf(): void
    {
        $this->securityHelper->method('validateCsrfToken')->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid CSRF token');

        $this->makeHandler();
    }

    public function testParseInputParametersRejectsInvalidType(): void
    {
        $this->get['type'] = 'invalid_type';

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid activity type filter');

        $this->makeHandler();
    }

    public function testHandleRequestReturnsEmptyOnNoQueries(): void
    {
        $this->get['type'] = 'badges';

        $handler = $this->makeHandler();

        // mock DB returning empty result
        $stmt = $this->createStub(PDOStatement::class);
        $stmt->method('fetchColumn')->willReturn(0);
        $stmt->method('fetch')->willReturn(false);
        $this->pdo->method('prepare')->willReturn($stmt);

        ob_start();
        $handler->handleRequest();
        $output = ob_get_clean();

        $data = json_decode($output, true);
        $this->assertTrue($data['success']);
        $this->assertEquals(0, $data['data']['total']);
    }

    public function testFormatDuration(): void
    {
        $handler = $this->makeHandler();
        $reflection = new ReflectionClass($handler);
        $method = $reflection->getMethod('formatDuration');

        $this->assertEquals('30s', $method->invoke($handler, 30));
        $this->assertEquals('5m', $method->invoke($handler, 300));
        $this->assertEquals('2h', $method->invoke($handler, 7200));
        $this->assertEquals('1d', $method->invoke($handler, 86400));
    }

    public function testInvalidDateRangeThrowsException(): void
    {
        $this->get['range'] = 'invalid_range';

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid date range filter');

        $this->makeHandler();
    }

    public function testInvalidCategoryFilterThrowsException(): void
    {
        $this->get['category'] = 'invalid';

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid category filter');

        $this->makeHandler();
    }

    public function testDatabaseErrorThrowsException(): void
    {
        $this->pdo->method('prepare')->willThrowException(new PDOException('Database error'));

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Database error occurred');

        $handler = $this->makeHandler();
        $handler->handleRequest();
    }

    public function testFormatTimeAgoInvalidDatetimeThrowsException(): void
    {
        $handler = $this->makeHandler();
        $reflection = new ReflectionClass($handler);
        $method = $reflection->getMethod('formatTimeAgo');

        $result = $method->invoke($handler, 'invalid-date');
        $this->assertEquals('Recently', $result);
    }

    // Tests requiring full DB setup

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testHandleRequestReturnsCorrectData(): void
    {
        $this->setupInMemoryDB();

        foreach ($this->activityTypes as $type) {
            foreach ($this->activityRanges as $range) {
                foreach ($this->challengeCategories as $category) {
                    $allActivities = [];
                    $page = 1;

                    do {
                        $this->get['type'] = $type !== 'flag_submitted' ? $type : 'all';
                        $this->get['range'] = $range;
                        $this->get['category'] = $category;
                        $this->get['page'] = $page;

                        $handler = $this->makeHandler();
                        ob_start();
                        $handler->handleRequest();
                        $output = ob_get_clean();

                        $data = json_decode($output, true);
                        $this->assertTrue($data['success']);

                        $allActivities = array_merge($allActivities, $data['data']['activities']);
                        $total = $data['data']['total'];
                        $page++;
                    } while (count($allActivities) < $total);

                    $typesToCheck = $type === 'all' || $type === 'flag_submitted'
                        ? array_filter($this->activityTypes, fn($t) => $t !== 'all')
                        : [$type];

                    // Determine if the activity should be included based on range
                    $rangesToCheck = match ($range) {
                        'today' => ['today'],
                        'week'  => ['today', 'week'],
                        'month' => ['today', 'week', 'month'],
                        'year', 'all' => ['today', 'week', 'month', 'year'],
                        default => throw new CustomException("Unknown range: $range"),
                    };

                    $expectedIds = [];
                    foreach ($typesToCheck as $t) {
                        $categoriesToCheck = $t !== 'badges' ? ($category === 'all' ? array_filter($this->challengeCategories, fn($c) => $c !== 'all') : [$category]) : ['all'];

                        foreach ($rangesToCheck as $r) {
                            foreach ($categoriesToCheck as $c) {
                                $expectedIds[] = $this->combinationToId($t, $r, $c);
                            }
                        }
                    }


                    $foundIds = array_column($allActivities, 'item_id');

                    sort($expectedIds);
                    sort($foundIds);

                    $this->assertEquals($expectedIds, $foundIds, "Mismatch for filter combination: type=$type, range=$range, category=$category");
                }
            }
        }
    }
}
