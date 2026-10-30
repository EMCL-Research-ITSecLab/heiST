<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\TestCase;

class AnnouncementsHandlerTest extends TestCase
{
    private $pdo;
    private $databaseHelper;
    private $securityHelper;
    private $logger;
    private $session;
    private $server;
    private $get;

    private array $config;
    private array $importanceLevels;
    private array $activityRanges;
    private $mockDB;

    protected function setUp(): void
    {
        $this->mockDB = null;
        $this->pdo = $this->createStub(PDO::class);
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);

        $this->securityHelper = $this->createStub(ISecurityHelper::class);
        $this->securityHelper
            ->method('validateSession')
            ->willReturn(true);
        $this->securityHelper
            ->method('validateCsrfToken')
            ->willReturn(true);

        $this->logger = new MockLogger();

        $this->session = new MockSession();
        $this->server = new MockServer();
        $this->get = new MockGet();

        $this->config = require __DIR__ . '/../../config/backend.config.php';
        $this->importanceLevels = $this->config['filters']['IMPORTANCE_LEVELS'];
        $this->activityRanges = $this->config['filters']['ACTIVITY_RANGES'];
    }

    private function getHandlerInstance(): AnnouncementsHandler {
        return new AnnouncementsHandler(
            $this->config,
            $this->databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get
        );
    }

    private function makeDateForRange(string $range): string
    {
        return match ($range) {
            'today' => date("Y-m-d H:i:s", strtotime("now")),
            'week'  => date("Y-m-d H:i:s", strtotime("-3 days")),
            'month' => date("Y-m-d H:i:s", strtotime("-15 days")),
            'year'  => date("Y-m-d H:i:s", strtotime("-6 months")),
            'all'   => date("Y-m-d H:i:s", strtotime("-5 years")),
            default => throw new CustomException("Unknown range: $range"),
        };
    }

    private function announcementCombinationToId(string $importance, string $range): int
    {
        $importances = array_values(array_filter($this->importanceLevels, fn($i) => $i !== 'all'));
        $ranges = array_values(array_filter($this->activityRanges, fn($r) => $r !== 'all'));

        $i = array_search($importance, $importances, true);
        $r = array_search($range, $ranges, true);

        if ($i === false || $r === false) {
            throw new CustomException("Invalid announcement filter value: [$importance, $range]");
        }

        return $i * count($ranges) + $r + 1;
    }

    private function requireMockDB(): void {
        $this->mockDB = new MockPostgresDB();
        $this->pdo = $this->mockDB->getPDO();
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);
    }

    private function setupInMemoryAnnouncements(): void
    {
        $this->requireMockDB();

        $importances = array_values(array_filter($this->importanceLevels, fn($i) => $i !== 'all'));
        $ranges = array_values(array_filter($this->activityRanges, fn($r) => $r !== 'all'));

        foreach ($importances as $importance) {
            foreach ($ranges as $range) {
                $id = $this->announcementCombinationToId($importance, $range);
                $createdAt = $this->makeDateForRange($range);

                $this->pdo->prepare("
                INSERT INTO announcements (id, title, content, importance, created_at, category, author)
                VALUES (?, ?, ?, ?, ?, 'general', 'admin')
            ")->execute([
                    $id,
                    "Announcement-$id",
                    "Content for announcement $id",
                    $importance,
                    $createdAt
                ]);
            }
        }
    }

    public function testInvalidSessionThrowsException(): void {
        $securityHelper = $this->createStub(ISecurityHelper::class);
        $securityHelper
            ->method('validateSession')
            ->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Unauthorized');
        $this->expectExceptionCode(401);

        new AnnouncementsHandler(
            $this->config,
            $this->databaseHelper,
            $securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get
        );
    }

    public function testInvalidCsrfTokenThrowsException(): void {
        $securityHelper = $this->createStub(ISecurityHelper::class);
        $securityHelper
            ->method('validateSession')
            ->willReturn(true);
        $securityHelper
            ->method('validateCsrfToken')
            ->willReturn(false);

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid CSRF token');
        $this->expectExceptionCode(403);

        new AnnouncementsHandler(
            $this->config,
            $this->databaseHelper,
            $securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get
        );
    }

    public function testInvalidImportanceValueThrowsException(): void {
        $this->get['importance'] = 'invalid';

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid importance value');
        $this->expectExceptionCode(400);

        $this->getHandlerInstance();
    }

    public function testInvalidDateRangeValueThrowsException(): void {
        $this->get['range'] = 'invalid';

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Invalid date range value');
        $this->expectExceptionCode(400);

        $this->getHandlerInstance();
    }

    public function testDatabaseErrorThrowsException(): void {
        $pdo = $this->createStub(PDO::class);
        $pdo
            ->method('prepare')
            ->willThrowException(new PDOException("Simulated DB error"));

        $databaseHelper = $this->createStub(IDatabaseHelper::class);
        $databaseHelper
            ->method('getPDO')
            ->willReturn($pdo);

        $handler = new AnnouncementsHandler(
            $this->config,
            $databaseHelper,
            $this->securityHelper,
            $this->logger,
            $this->session,
            $this->server,
            $this->get
        );

        $this->expectException(Exception::class);
        $this->expectExceptionMessage('Database error occurred');
        $this->expectExceptionCode(500);

        $handler->handleRequest();
    }

    // tests requiring in-memory announcements

    #[\PHPUnit\Framework\Attributes\Group('database')]
    public function testCorrectAnnouncementsFetched(): void
    {
        $this->setupInMemoryAnnouncements();
        $this->databaseHelper = $this->createStub(IDatabaseHelper::class);
        $this->databaseHelper
            ->method('getPDO')
            ->willReturn($this->pdo);


        foreach ($this->activityRanges as $range) {
            foreach ($this->importanceLevels as $importance) {
                $importanceToCheck = $importance === 'all' ? array_values(array_filter($this->importanceLevels, fn($i) => $i !== 'all')) : [$importance];
                $rangeToCheck = match ($range) {
                    'all' => array_values(array_filter($this->activityRanges, fn($r) => $r !== 'all')),
                    'today' => ['today'],
                    'week' => ['today', 'week'],
                    'month' => ['today', 'week', 'month'],
                    'year' => ['today', 'week', 'month', 'year'],
                    default => throw new CustomException("Unknown range: $range"),
                };

                $fetchedIds = [];
                $page = 1;

                do {
                    $get = new MockGet();
                    $get['importance'] = $importance;
                    $get['range'] = $range;
                    $get['page'] = $page;

                    $handler = new AnnouncementsHandler(
                        $this->config,
                        $this->databaseHelper,
                        $this->securityHelper,
                        $this->logger,
                        $this->session,
                        $this->server,
                        $get
                    );

                    ob_start();
                    $handler->handleRequest();
                    $outputJson = ob_get_clean();
                    $output = json_decode($outputJson, true);

                    $totalPages = $output['data']['total_pages'] ?? 1;
                    $page++;

                    $fetchedIds = array_merge($fetchedIds, array_map(fn($a) => (int)$a['id'], $output['data']['announcements'] ?? []));

                } while ($page <= $totalPages);

                $expectedIds = [];
                foreach ($importanceToCheck as $imp) {
                    foreach ($rangeToCheck as $rng) {
                        $expectedIds[] = $this->announcementCombinationToId($imp, $rng);
                    }
                }

                sort($expectedIds);
                sort($fetchedIds);
                $this->assertEquals($expectedIds, $fetchedIds, "Failed for combination: [$importance, $range]");
            }
        }
    }
}
