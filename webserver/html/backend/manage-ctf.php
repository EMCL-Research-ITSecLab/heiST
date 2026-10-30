<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class CTFManagementHandler
{
    private PDO $pdo;
    private int $userId;
    private string $method;
    private array $inputData;
    private array $config;
    private array $generalConfig;
    private $route;

    private IDatabaseHelper $databaseHelper;
    private ISecurityHelper $securityHelper;
    private ILogger $logger;
    private IAuthHelper $authHelper;
    private ICurlHelper $curlHelper;
    private IChallengeHelper $challengeHelper;

    private ISession $session;
    private IServer $server;
    private IGet $get;
    private IPost $post;
    private ICookie $cookie;
    
    private ISystem $system;

    /**
     * @throws Exception
     */
    public function __construct(
        array $config,
        array $generalConfig,
        
        IDatabaseHelper $databaseHelper = null,
        ISecurityHelper $securityHelper = null,
        ILogger $logger = null,
        IAuthHelper $authHelper = null,
        ICurlHelper $curlHelper = null,
        IChallengeHelper $challengeHelper = null,
        
        ISession $session = new Session(),
        IServer $server = new Server(),
        IGet $get = new Get(),
        IPost $post = new Post(),
        
        ISystem $system = new SystemWrapper(),
        IEnv $env = new Env(),
        ICookie $cookie = new Cookie()
    )
    {
        $this->session = $session;
        $this->server = $server;
        $this->get = $get;
        $this->post = $post;
        $this->cookie = $cookie;
        $this->route = "/manage-ctf";

        $this->databaseHelper = $databaseHelper ?? new DatabaseHelper($logger, $system);
        $this->securityHelper = $securityHelper ?? new SecurityHelper($logger, $session, $system);
        $this->logger = $logger ?? new Logger(route: $this->route, system: $system);
        $this->authHelper = $authHelper ?? new AuthHelper($logger, $system, $env);
        $this->curlHelper = $curlHelper ?? new CurlHelper($env);
        $this->challengeHelper = $challengeHelper ?? new ChallengeHelper();
        
        $this->system = $system;

        $this->config = $config;
        $this->generalConfig = $generalConfig;
        header('Content-Type: application/json');
        $this->pdo = $this->databaseHelper->getPDO();
        $this->initSession();
        $this->validateAccess();
        $this->userId = $this->session['user_id'];
        $this->method = $this->server['REQUEST_METHOD'];
        $this->inputData = $this->parseInputData();

        $this->logger->logDebug("Initialized CTFManagementHandler for user ID: $this->userId");
    }

    private function initSession(): void
    {
        try {
            $this->securityHelper->initSecureSession();
        } catch (CustomException $e) {
            $this->logger->logError("Session initialization failed: " . $e->getMessage());
            throw new CustomException('Session initialization error', 500);
        } catch (Exception $e) {
            $this->logger->logError("Unexpected error during session initialization: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    /**
     * @throws Exception
     */
    private function validateAccess(): void
    {
        if (!$this->securityHelper->validateSession()) {
            $this->logger->logWarning("Unauthorized access attempt to manage CTF - IP: " . $this->logger->anonymizeIp($this->server['REMOTE_ADDR'] ?? 'unknown'));
            throw new CustomException('Unauthorized - Please login', 401);
        }

        $csrfToken = $this->cookie['csrf_token'] ?? '';
        if (!$this->securityHelper->validateCsrfToken($csrfToken)) {
            $this->logger->logWarning("Invalid CSRF token in manage CTF - User ID: " . ($this->session['user_id'] ?? 'unknown') . "");
            throw new CustomException('Invalid CSRF token', 403);
        }

        if (!$this->securityHelper->validateAdminAccess($this->pdo)) {
            $this->logger->logWarning("Non-admin access attempt to manage CTF - User ID: " . ($this->session['user_id'] ?? 'unknown'));
            throw new CustomException('Unauthorized - Admin access only', 403);
        }
    }

    private function parseInputData(): array
    {
        if ($this->method === 'GET') {
            return $this->get->all();
        }

        if ($this->method === 'DELETE') {
            $data = json_decode($this->system->file_get_contents('php://input'), true);
            if (json_last_error() !== JSON_ERROR_NONE) {
                $this->logger->logError("Invalid JSON in CTF deletion - User ID: $this->userId");
                throw new CustomException('Invalid JSON data', 400);
            }
            return $data;
        }

        return $this->post->all();
    }

    public function handleRequest(): void
    {
        try {
            switch ($this->method) {
                case 'GET':
                    $this->handleGetRequest();
                    break;
                case 'POST':
                    $this->handlePostRequest();
                    break;
                case 'DELETE':
                    $this->handleDeleteRequest();
                    break;
                default:
                    $this->logger->logWarning("Invalid method in manage CTF - Method: $this->method, User ID: $this->userId");
                    throw new CustomException('Method not allowed', 405);
            }
        } catch (CustomException $e) {
            $this->handleError($e);
        } catch (Exception $e) {
            // most likely not reachable, gonna leave it here for safety
            $this->logger->logError("Unexpected error in CTF management: " . $e->getMessage() . "\n" . $e->getTraceAsString());
            $this->handleError(new Exception('Internal Server Error', 500));
        }
    }

    private function handleGetRequest(): void
    {
        $action = $this->inputData['action'] ?? null;

        switch($action) {
            case 'get_challenges':
                $this->handleGetChallenges();
                break;
            case 'get_leaderboard':
                $this->handleLeaderboard();
                break;
            default:
                $this->handleGetChallenges();
        }
    }

    private function handleGetChallenges(): void
    {
        $challenges = $this->getChallenges();
        $stats = $this->getChallengeStats();

        echo json_encode([
            'success' => true,
            'challenges' => $challenges,
            'stats' => $stats
        ]);
    }

    private function handleLeaderboard(): void
   {
       if (!isset($this->inputData['id'])) {
           echo json_encode(['success' => false, 'message' => 'Challenge ID is required']);
           defined('PHPUNIT_RUNNING') || exit;
       }

       $challengeId = (int)$this->inputData['id'];
       $page = isset($this->inputData['page']) ? (int)$this->inputData['page'] : 1;
       $limit = isset($this->inputData['limit']) ? (int)$this->inputData['limit'] : 10;
       $offset = ($page - 1) * $limit;

       try {
           $stmt = $this->pdo->prepare("
                SELECT get_creator_id_by_challenge_id(:challenge_id) AS creator_id
            ");
           $stmt->execute(['challenge_id' => $challengeId]);
           $creatorId = $stmt->fetchColumn();

           if ($creatorId !== $this->userId) {
               echo json_encode(['success' => false, 'message' => 'You are not authorized to view this leaderboard']);
               defined('PHPUNIT_RUNNING') || exit;
           }

           $leaderboard = $this->challengeHelper->getChallengeLeaderboard($this->pdo, $challengeId, $limit, $offset);

           $stmt = $this->pdo->prepare("
                SELECT get_total_leaderboard_entries_for_author(:challenge_id)
            ");
           $stmt->execute(['challenge_id' => $challengeId]);
           $total = $stmt->fetchColumn();

           echo json_encode([
               'success' => true,
               'leaderboard' => $leaderboard,
               'total_entries' => $total
           ]);
       } catch (PDOException) {
           echo json_encode(['success' => false, 'message' => 'Error getting leaderboard']);
       }
   }

    private function handlePostRequest(): void
    {
        $action = $this->inputData['action'] ?? null;

        switch ($action) {
            case 'update_challenge':
                $this->handleUpdateChallenge();
                break;
            case 'restore_challenge':
                $this->handleRestoreRequest();
                break;
            default:
                throw new CustomException('Invalid action', 400);
        }
    }

    private function handleUpdateChallenge(): void
    {
        $errors = $this->validateChallengeData();
        if (!empty($errors['errors'])) {
            $this->logger->logWarning("Validation failed in CTF update - User ID: $this->userId, Errors: " . implode(', ', $errors['errors']));
            http_response_code(400);
            echo json_encode($errors);
            defined('PHPUNIT_RUNNING') || exit;
        }

        $challenge = $this->verifyChallengeOwnershipAndStatus((int)$this->inputData['id']);

        if ($challenge['marked_for_deletion'] && !empty($this->inputData['isActive'])) {
            $this->logger->logWarning("Attempt to activate deleted challenge - ID: {$this->inputData['id']}, User ID: $this->userId");
            http_response_code(400);
            echo json_encode([
                'success' => false,
                'message' => 'Cannot activate a challenge marked for deletion. Restore it first.',
                'fields' => ['edit-active']
            ]);
            defined('PHPUNIT_RUNNING') || exit;
        }

        $this->updateChallenge();

        $this->logger->logInfo("CTF challenge updated - ID: {$this->inputData['id']}, Name: {$this->inputData['name']}, User ID: $this->userId");

        echo json_encode([
            'success' => true,
            'message' => 'Challenge updated successfully'
        ]);
    }

    private function handleRestoreRequest(): void
    {
        if (empty($this->inputData['id'])) {
            throw new CustomException('Challenge ID is required', 400);
        }

        $challengeId = (int)$this->inputData['id'];
        $challenge = $this->verifyChallengeOwnershipAndStatus($challengeId);

        if (!$challenge['marked_for_deletion']) {
            $this->logger->logWarning("Attempt to restore non-deleted challenge - ID: $challengeId, User ID: $this->userId");
            throw new CustomException('Challenge is not marked for deletion', 400);
        }

        $this->restoreChallenge($challengeId);

        $this->logger->logInfo("CTF challenge restored - ID: $challengeId, User ID: $this->userId");

        echo json_encode([
            'success' => true,
            'message' => 'Challenge restored successfully'
        ]);
    }

    private function validateChallengeData(): array
    {
        $errors = ['errors' => [], 'fields' => []];
        $input = $this->inputData;

        if (empty($input['name'])) {
            $errors['errors'][] = 'Challenge name is required';
            $errors['fields'][] = 'edit-name';
        } elseif (strlen($input['name']) > $this->generalConfig['ctf']['MAX_CTF_NAME_LENGTH']) {
            $errors['errors'][] = 'Name cannot exceed ' . $this->generalConfig['ctf']['MAX_CTF_NAME_LENGTH'] . ' characters';
            $errors['fields'][] = 'edit-name';
        } else {
            $stmt = $this->pdo->prepare("
                SELECT get_challenge_template_id_by_name_with_possible_exclude(:name, :exclude_id) AS exists
            ");

            $stmt->execute([
                'name' => $input['name'],
                'exclude_id' => isset($input['id']) ? (int)$input['id'] : null
            ]);

            if ($stmt->fetchColumn()) {
                $errors['errors'][] = 'A challenge with this name already exists';
                $errors['fields'][] = 'edit-name';
            }
        }

        if (empty($input['description'])) {
            $errors['errors'][] = 'Description is required';
            $errors['fields'][] = 'edit-description';
        } elseif (strlen($input['description']) > $this->generalConfig['ctf']['MAX_CTF_DESCRIPTION_LENGTH']) {
            $errors['errors'][] = 'Description cannot exceed ' . $this->generalConfig['ctf']['MAX_CTF_DESCRIPTION_LENGTH'] . ' characters';
            $errors['fields'][] = 'edit-description';
        }

        if (empty($input['category']) || !in_array($input['category'], $this->config['challenge']['VALID_CATEGORIES'])) {
            $errors['errors'][] = 'Please select a valid category';
            $errors['fields'][] = 'edit-category';
        }

        if (!in_array($input['difficulty'], $this->config['challenge']['VALID_DIFFICULTIES'])) {
            $errors['errors'][] = 'Please select a valid difficulty level';
            $errors['fields'][] = 'edit-difficulty';
        }

        if (strlen($input['hint'] ?? '') > $this->generalConfig['ctf']['MAX_GENERAL_HINT_LENGTH']) {
            $errors['errors'][] = 'Hint cannot exceed ' . $this->generalConfig['ctf']['MAX_GENERAL_HINT_LENGTH'] . ' characters';
            $errors['fields'][] = 'edit-hint';
        }

        if (strlen($input['solution'] ?? '') > $this->generalConfig['ctf']['MAX_SOLUTION_LENGTH']) {
            $errors['errors'][] = 'Solution cannot exceed ' . $this->generalConfig['ctf']['MAX_SOLUTION_LENGTH'] . ' characters';
            $errors['fields'][] = 'edit-solution';
        }

        return $errors;
    }

    private function verifyChallengeOwnershipAndStatus(int $challengeId): array
    {
        $stmt = $this->pdo->prepare("
            SELECT
                id,
                marked_for_deletion
            FROM get_challenge_template_data_for_deletion(:user_id, :id)
        ");
        $stmt->execute(['id' => $challengeId, 'user_id' => $this->userId]);
        $challenge = $stmt->fetch(PDO::FETCH_ASSOC);

        if (!$challenge) {
            $this->logger->logError("Challenge not found or access denied - Challenge ID: $challengeId, User ID: $this->userId");
            throw new CustomException('Challenge not found or access denied', 404);
        }

        return $challenge;
    }

    private function updateChallenge(): void
    {
        $isActive = (int)filter_var($this->inputData['isActive'], FILTER_VALIDATE_BOOLEAN);

        $stmt = $this->pdo->prepare("SELECT challenge_template_is_marked_for_deletion(:id) AS marked_for_deletion");
        $stmt->execute(['id' => $this->inputData['id']]);
        $challenge = $stmt->fetch();

        if ($challenge['marked_for_deletion']) {
            $isActive = 0;
        }

        $stmt = $this->pdo->prepare("
            SELECT update_challenge_template(
                :id,
                :name,
                :description,
                :category,
                :difficulty,
                :hint,
                :solution,
                :is_active
            )
        ");

        $stmt->execute([
            'id' => $this->inputData['id'],
            'name' => $this->inputData['name'],
            'description' => $this->inputData['description'],
            'category' => $this->inputData['category'],
            'difficulty' => $this->inputData['difficulty'],
            'hint' => !empty($this->inputData['hint']) ? $this->inputData['hint'] : null,
            'solution' => !empty($this->inputData['solution']) ? $this->inputData['solution'] : null,
            'is_active' => $isActive
        ]);
    }

    private function restoreChallenge(int $challengeId): void
    {
        $stmt = $this->pdo->prepare("
            SELECT restore_challenge_template(:challenge_id)
        ");
        $stmt->execute(['challenge_id' => $challengeId]);
    }

    /**
     * @throws Exception
     */
    private function handleDeleteRequest(): void
    {
        $challengeId = $this->inputData['id'] ?? null;
        $forceDelete = $this->inputData['force'] ?? false;

        if (!$challengeId) {
            $this->logger->logError("Missing challenge ID in deletion - User ID: $this->userId");
            throw new CustomException('Challenge ID is required', 400);
        }

        $challenge = $this->verifyChallengeOwnershipForDeletion((int)$challengeId);
        $this->processDeletion((int)$challengeId, (boolean)$forceDelete, $challenge['name']);
    }

    private function verifyChallengeOwnershipForDeletion(int $challengeId): array
    {
        $stmt = $this->pdo->prepare("
            SELECT id, name FROM verify_challenge_template_ownership_for_deletion(:user_id, :id)
        ");
        $stmt->execute(['id' => $challengeId, 'user_id' => $this->userId]);
        $challenge = $stmt->fetch();

        if (!$challenge) {
            $this->logger->logError("Challenge not found or access denied - Challenge ID: $challengeId, User ID: $this->userId");
            throw new CustomException('Challenge not found or access denied', 404);
        }

        return $challenge;
    }

    /**
     * @throws Exception
     */
    private function processDeletion(int $challengeId, bool $forceDelete, string $challengeName): void
    {
        $this->pdo->beginTransaction();

        try {
            if ($forceDelete) {
                $this->forceDeleteChallenge($challengeId);
                $message = 'Challenge and all instances permanently deleted';
                $this->logger->logInfo("Force deleted challenge - ID: $challengeId, Name: '$challengeName'");
            } else {
                $message = $this->softDeleteChallenge($challengeId);
                $this->logger->logInfo("Soft deleted challenge - ID: $challengeId, Name: '$challengeName'");
            }

            $this->pdo->commit();

            echo json_encode([
                'success' => true,
                'message' => $message
            ]);
        } catch (CustomException $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Failed to delete CTF challenge - ID: $challengeId, Name: '$challengeName', Error: " . $e->getMessage());
            throw $e;
        } catch (Exception $e) {
            $this->pdo->rollBack();
            $this->logger->logError("Unexpected error during challenge deletion - ID: $challengeId, Name: '$challengeName', Error: " . $e->getMessage());
            throw new Exception('Internal Server Error', 500);
        }
    }

    private function forceDeleteChallenge(int $challengeId): void
    {

        $this->markChallengeForDeletion($challengeId);
        $this->stopRunningInstances($challengeId);
        $this->deleteVmTemplates($challengeId);
        $this->deleteRelatedDatabaseEntries($challengeId);
    }

    private function markChallengeForDeletion(int $challengeId): void
    {
        $stmt = $this->pdo->prepare("
            SELECT mark_challenge_template_for_deletion(:challenge_id)
        ");
        $stmt->execute(['challenge_id' => $challengeId]);
    }

    private function stopRunningInstances(int $challengeId): void
    {
        $stmt = $this->pdo->prepare("
            SELECT id, user_id, challenge_id FROM get_running_instances_of_challenge_template(:challenge_id)
        ");
        $stmt->execute(['challenge_id' => $challengeId]);
        $runningInstances = $stmt->fetchAll(PDO::FETCH_ASSOC);

        foreach ($runningInstances as $instance) {
            $response = $this->curlHelper->makeBackendRequest(
                '/stop-challenge',
                'POST',
                $this->authHelper->getBackendHeaders(),
                ['user_id' => $instance['user_id']]
            );

            if (!$response['success']) {
                throw new CustomException('Failed to stop challenge instance');
            }
        }
    }

    private function deleteVmTemplates(int $challengeId): void
    {
        $response = $this->curlHelper->makeBackendRequest(
            '/delete-machine-templates',
            'POST',
            $this->authHelper->getBackendHeaders(),
            ['challenge_id' => $challengeId]
        );

        if (!$response['success']) {
            throw new CustomException('Failed to delete VM templates');
        }
    }

    private function deleteRelatedDatabaseEntries(int $challengeId): void
    {
        $stmt = $this->pdo->prepare("SELECT delete_challenge_template(:challenge_id)");
        $stmt->execute(['challenge_id' => $challengeId]);

    }

    private function softDeleteChallenge(int $challengeId): string
    {
        $activeDeployments = $this->countActiveDeployments($challengeId);

        if ($activeDeployments > 0) {
            $this->markChallengeForSoftDeletion($challengeId);
            return 'Challenge marked for deletion (will be removed when all instances complete)';
        }

        $this->deleteVmTemplates($challengeId);
        $this->deleteRelatedDatabaseEntries($challengeId);
        return 'Challenge deleted successfully (no active instances)';
    }

    private function countActiveDeployments(int $challengeId): int
    {
        $stmt = $this->pdo->prepare("
            SELECT count_active_deployments_of_challenge_template(:challenge_id) AS active_count
        ");
        $stmt->execute(['challenge_id' => $challengeId]);
        return $stmt->fetchColumn();
    }

    private function markChallengeForSoftDeletion(int $challengeId): void
    {
        $stmt = $this->pdo->prepare("
            SELECT mark_challenge_template_for_soft_deletion(:challenge_id)
        ");
        $stmt->execute(['challenge_id' => $challengeId]);
    }

    private function getChallenges(): array
    {
        $stmt = $this->pdo->prepare("
            SELECT
                id,
                name,
                description,
                category,
                difficulty,
                image_path,
                is_active,
                created_at,
                marked_for_deletion,
                total_deployments,
                hint,
                solution,
                active_deployments,
                solve_count,
                avg_completion_minutes
            FROM get_challenge_templates_for_management(:user_id)
       ");
        $stmt->execute(['user_id' => $this->userId]);
        return $stmt->fetchAll(PDO::FETCH_ASSOC);
    }

    private function getChallengeStats(): array
    {
        $stats = [];

        $stmt = $this->pdo->prepare("SELECT get_challenge_template_count_for_user(:user_id) AS total_count");
        $stmt->execute(['user_id' => $this->userId]);
        $stats['total_challenges'] = $stmt->fetchColumn();

        $stmt = $this->pdo->prepare("
            SELECT get_active_deployments_of_challenge_templates_by_user(:user_id) AS active_count
        ");
        $stmt->execute(['user_id' => $this->userId]);
        $stats['active_deployments'] = $stmt->fetchColumn();

        $stmt = $this->pdo->prepare("
            SELECT get_total_deployments_of_challenge_templates_by_user(:user_id) AS total_deployments
        ");
        $stmt->execute(['user_id' => $this->userId]);
        $stats['total_deployments'] = $stmt->fetchColumn();

        $stmt = $this->pdo->prepare("
            SELECT get_average_completion_time_of_challenge_templates_by_user(:user_id) AS avg_minutes
        ");
        $stmt->execute(['user_id' => $this->userId]);
        $stats['avg_completion_minutes'] = $stmt->fetchColumn();

        return $stats;
    }

    private function handleError(Exception $e): void
    {
        $errorCode = $e->getCode() ?: 500;
        $errorMessage = $errorCode >= 500 ? 'An internal server error occurred' : $e->getMessage();

        if ($errorCode === 401) {
            $this->session->unset();
            $this->session->destroy();
            $this->logger->logWarning("Session destroyed due to unauthorized access");
        }

        if ($errorCode >= 500) {
            $this->logger->logError("Internal error in CTF management: " . $e->getMessage() . "\n" . $e->getTraceAsString());
        } else {
            $this->logger->logWarning("CTF management error: " . $e->getMessage());
        }

        http_response_code($errorCode);
        echo json_encode([
            'success' => false,
            'message' => $errorMessage,
            'redirect' => $errorCode === 401 ? '/login' : null
        ]);
        defined('PHPUNIT_RUNNING') || exit;
    }
}

// @codeCoverageIgnoreStart

if(defined('PHPUNIT_RUNNING'))
    return;

try {
    $config = require __DIR__ . '/../config/backend.config.php';
    $system = new SystemWrapper();
    $generalConfig = json_decode($system->file_get_contents(__DIR__ . '/../config/general.config.json'), true);

    $handler = new CTFManagementHandler(config: $config, generalConfig: $generalConfig);
    $handler->handleRequest();
} catch (CustomException $e) {
    $errorCode = $e->getCode() ?: 500;
    http_response_code($errorCode);
    $logger = new Logger("/manage-ctf");
    $logger->logError("Error in manage-ctf endpoint: " . $e->getMessage() . " (Code: $errorCode)");
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
    $logger = new Logger("/manage-ctf");
    $logger->logError("Unexpected error in manage-ctf endpoint: " . $e->getMessage() . "\n" . $e->getTraceAsString());
    echo json_encode([
        'success' => false,
        'message' => 'An unexpected error occurred'
    ]);
}

// @codeCoverageIgnoreEnd
