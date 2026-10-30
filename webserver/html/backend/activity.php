<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class ActivitiesHandler
{
    private PDO $pdo;
    private ?int $userId;
    private int $page;
    private int $perPage = 10;
    private string $typeFilter;
    private string $rangeFilter;
    private string $categoryFilter;
    private array $config;
    private string $route;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;

    private ISession $session;
    private IServer $server;
    private IGet $get;
    private ICookie $cookie;


    /**
     * @throws Exception
     */
    public function __construct(
        array $config,

        IDatabaseHelper $databaseHelper = null,
        ISecurityHelper $securityHelper = null,
        ILogger $logger = null,

        ISession $session = new Session(),
        IServer $server = new Server(),
        IGet $get = new Get(),

        ISystem $system = new SystemWrapper(),
        ICookie $cookie = new Cookie()
    )
    {
        $this->session = $session;
        $this->server = $server;
        $this->get = $get;
        $this->cookie = $cookie;
        $this->route = "/activity";

        $this->logger = $logger ?? new Logger(route: $this->route,system: $system);
        $this->databaseHelper = $databaseHelper ?? new DatabaseHelper($logger, $system);
        $this->securityHelper = $securityHelper ?? new SecurityHelper($logger, $session, $system);
        

        $this->config = $config;
        $this->initSession();
        $this->validateRequest();
        $this->pdo = $this->databaseHelper->getPDO();
        $this->userId = $this->session['user_id'];
        $this->parseInputParameters();
        $this->logger->logDebug("Initialized ActivitiesHandler for user ID: $this->userId");
    }

    /**
     * @throws Exception
     */
    private function initSession(): void
    {
        $this->securityHelper->initSecureSession();

        if (!$this->securityHelper->validateSession()) {
            $this->logger->logWarning('Unauthorized access attempt to activities route');
            throw new CustomException('Unauthorized', 401);
        }
    }

    /**
     * @throws Exception
     */
    private function validateRequest(): void
    {
        $csrfToken = $this->cookie['csrf_token'] ?? '';
        if (!$this->securityHelper->validateCsrfToken($csrfToken)) {
            $this->logger->logWarning('Invalid CSRF token attempt from user ID: ' . ($this->session['user_id'] ?? 'unknown'));
            throw new CustomException('Invalid CSRF token', 403);
        }
    }

    /**
     * @throws Exception
     */
    private function parseInputParameters(): void
    {
        $this->page = (int)$this->get['page'] ?? 1;
        $this->page = max(1, $this->page);

        $this->typeFilter = $this->get['type'] ?? 'all';
        if (!in_array($this->typeFilter, $this->config['filters']['ACTIVITY_TYPES'])) {
            $this->logger->logWarning('Invalid type filter provided: ' . $this->typeFilter);
            throw new CustomException('Invalid activity type filter', 400);
        }

        $this->rangeFilter = $this->get['range'] ?? 'all';
        if (!in_array($this->rangeFilter, $this->config['filters']['ACTIVITY_RANGES'])) {
            $this->logger->logWarning('Invalid range filter provided: ' . $this->rangeFilter);
            throw new CustomException('Invalid date range filter', 400);
        }

        $this->categoryFilter = $this->get['category'] ?? 'all';
        if (!in_array($this->categoryFilter, $this->config['filters']['CHALLENGE_CATEGORIES'])) {
            $this->logger->logWarning('Invalid category filter provided: ' . $this->categoryFilter);
            throw new CustomException('Invalid category filter', 400);
        }
    }

    /**
     * @throws Exception
     */
    public function handleRequest(): void
    {
        try {
            $total = $this->getTotalCount();
            $activities = $this->getPaginatedResults();

            $this->sendResponse($activities, $total);
        } catch (PDOException $e) {
            $this->logger->logError("Database error in activities route: " . $e->getMessage());
            throw new CustomException('Database error occurred', 500);
        }
    }

    private function getTotalCount(): int
    {
        $stmt = $this->pdo->prepare("
            SELECT get_user_activities_total_count(
                :user_id,
                :category_filter,
                :type_filter,
                :date_range
            ) AS total_count
        ");

        $stmt->bindValue(':user_id', $this->userId, PDO::PARAM_INT);
        $stmt->bindValue(':category_filter', $this->categoryFilter !== 'all' ? $this->categoryFilter : null);
        $stmt->bindValue(':type_filter', $this->typeFilter !== 'all' ? $this->typeFilter : null);
        $stmt->bindValue(':date_range', $this->rangeFilter !== 'all' ? $this->rangeFilter : null);

        $stmt->execute();

        return $stmt->fetchColumn();
    }

    private function getPaginatedResults(): array
    {
        $offset = ($this->page - 1) * $this->perPage;
        $stmt = $this->pdo->prepare("
            SELECT 
                activity_type,
                item_id,
                item_name,
                category,
                points,
                solved,
                attempt_number,
                started_at,
                completed_at,
                status,
                activity_date,
                icon,
                color,
                description,
                item_type,
                flag_id
            FROM get_user_activities(
                :user_id,
                :category_filter,
                :type_filter,
                :date_range,
                :limit,
                :offset
            )
        ");

        $stmt->bindValue(':user_id', $this->userId, PDO::PARAM_INT);
        $stmt->bindValue(':category_filter', $this->categoryFilter !== 'all' ? $this->categoryFilter : null);
        $stmt->bindValue(':type_filter', $this->typeFilter !== 'all' ? $this->typeFilter : null);
        $stmt->bindValue(':date_range', $this->rangeFilter !== 'all' ? $this->rangeFilter : null);
        $stmt->bindValue(':limit', $this->perPage, PDO::PARAM_INT);
        $stmt->bindValue(':offset', $offset, PDO::PARAM_INT);

        $stmt->execute();

        $activities = [];

        while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
            $activities[] = $this->formatActivity($row);
        }

        return $activities;
    }

    private function formatActivity($row): array
    {
        $activity = [
            'type' => $row['status'],
            'title' => '',
            'item_id' => $row['item_id'],
            'item_name' => $row['item_name'],
            'item_type' => $row['item_type'],
            'category' => $row['category'],
            'points' => $row['points'],
            'timestamp' => $row['activity_date'],
            'time_ago' => $this->formatTimeAgo($row['activity_date']),
            'attempt_number' => $row['attempt_number'],
            'icon' => $row['icon'],
            'color' => $row['color'],
            'description' => $row['description']
        ];

        switch ($row['item_type']) {
            case 'badge':
                $activity['title'] = 'Badge earned: ' . $row['item_name'];
                break;

            case 'challenge':
                $activity['title'] = match ($row['status']) {
                    'solved' => 'Challenge solved (Attempt #' . $row['attempt_number'] . ')',
                    'failed' => 'Challenge failed (Attempt #' . $row['attempt_number'] . ')',
                    'flag_submitted' => 'Flag submitted',
                    default => 'Challenge attempt #' . $row['attempt_number']
                };

                if ($row['completed_at']) {
                    $elapsedSeconds = strtotime($row['completed_at']) - strtotime($row['started_at']);
                    $activity['duration'] = $this->formatDuration($elapsedSeconds);
                } else {
                    $activity['duration'] = 'In progress';
                }
                break;
        }

        return $activity;
    }

    private function sendResponse($activities, $total): void
    {
        echo json_encode([
            'success' => true,
            'data' => [
                'activities' => $activities,
                'total' => (int)$total,
                'page' => $this->page,
                'per_page' => $this->perPage
            ]
        ]);
    }

    private function formatTimeAgo($datetime): string
    {
        if (!$datetime) return 'Recently';

        try {
            $now = new DateTime();
            $then = new DateTime($datetime);
            $diff = $now->diff($then);

            if ($diff->y > 0) return $diff->y . ' year' . ($diff->y > 1 ? 's' : '') . ' ago';
            if ($diff->m > 0) return $diff->m . ' month' . ($diff->m > 1 ? 's' : '') . ' ago';
            if ($diff->d > 0) return $diff->d . ' day' . ($diff->d > 1 ? 's' : '') . ' ago';
            if ($diff->h > 0) return $diff->h . ' hour' . ($diff->h > 1 ? 's' : '') . ' ago';
            if ($diff->i > 0) return $diff->i . ' minute' . ($diff->i > 1 ? 's' : '') . ' ago';
            return 'Just now';
        } catch (CustomException $e) {
            $this->logger->logError("Error formatting time ago: " . $e->getMessage());
            return 'Recently';
        } catch (Throwable $e) {
            $this->logger->logError("Unexpected error: " . $e->getMessage());
            return 'Recently';
        }
    }

    private function formatDuration($seconds): string
    {
        if ($seconds < 60) return round($seconds) . 's';
        if ($seconds < 3600) return round($seconds / 60) . 'm';
        if ($seconds < 86400) return round($seconds / 3600, 1) . 'h';
        return round($seconds / 86400, 1) . 'd';
    }
}

// @codeCoverageIgnoreStart

if(defined('PHPUNIT_RUNNING'))
    return;

try {
    header('Content-Type: application/json');
    $config = require __DIR__ . '/../config/backend.config.php';

    $handler = new ActivitiesHandler(config: $config);
    $handler->handleRequest();
} catch (CustomException $e) {
    $errorCode = $e->getCode() ?: 500;
    http_response_code($errorCode);
    $logger = new Logger("/activity");
    $logger->logError("Error in activity endpoint: " . $e->getMessage() . " (Code: $errorCode)");
    $response = [
        'success' => false,
        'message' => $e->getMessage()
    ];

    if ($errorCode === 401) {
        $response['redirect'] = '/login';
    }

    echo json_encode($response);
} catch (Exception $e) {
    http_response_code(500);
    $logger = new Logger("/activity");
    $logger->logError("Unexpected error in activity endpoint: " . $e->getMessage());
    $response = [
        'success' => false,
        'message' => 'An unexpected error occurred'
    ];
    echo json_encode($response);
}

// @codeCoverageIgnoreEnd