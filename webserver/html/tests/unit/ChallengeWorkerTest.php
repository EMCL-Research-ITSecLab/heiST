<?php
declare(strict_types=1);

require_once __DIR__ . '/../../vendor/autoload.php';

use PHPUnit\Framework\TestCase;

class ChallengeWorkerTest extends TestCase
{
    private PDO $pdo;
    private IDatabaseHelper $databaseHelper;
    private ICurlHelper $curlHelper;
    private IAuthHelper $authHelper;
    private $mockDB;

    private IEnv $env;
    private ILogger $logger;
    private ISystem $system;

    public function setUp(): void
    {
        $this->databaseHelper = $this->createMock(IDatabaseHelper::class);
        $this->curlHelper = $this->createMock(ICurlHelper::class);
        $this->authHelper = $this->createMock(IAuthHelper::class);

        $this->mockDB = null;
        $this->pdo = $this->createMock(PDO::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);

        $this->env = new Env(__DIR__ . '/../../../../setup');
        $this->logger = new MockLogger();
        $this->system = $this->createMock(ISystem::class);
    }

    private function requireMockDB(): void {
        $this->mockDB = new MockPostgresDB();
        $this->pdo = $this->mockDB->getPDO();
        $this->databaseHelper = $this->createMock(IDatabaseHelper::class);
        $this->databaseHelper->method('getPDO')->willReturn($this->pdo);
    }

    private function getHandler(): ChallengeWorker
    {
        return new ChallengeWorker(
            $this->databaseHelper,
            $this->curlHelper,
            $this->authHelper,
            false,
            $this->system,
            $this->env,
            $this->logger
        );
    }

    // Tests requiring a mock DB

    public function testNoExpiredChallenges(): void
    {
        $this->requireMockDB();

        ob_start();
        $handler = $this->getHandler();
        $handler->run();
        $output = ob_get_clean();

        $this->assertStringContainsString("No expired challenges found.", $output);
    }

    public function testExpiredChallengeGetsProcessed(): void
    {
        $this->requireMockDB();

        // Insert a challenge template
        $this->pdo->exec("
            INSERT INTO challenge_templates (id, name, difficulty, category)
            VALUES (1, 'Test Challenge', 'easy', 'web');
        ");

        // Insert an expired challenge
        $this->pdo->exec("INSERT INTO challenges (id, challenge_template_id, expires_at) VALUES (1, 1, CURRENT_TIMESTAMP - INTERVAL '1 hour');");
        $this->pdo->exec("INSERT INTO completed_challenges (id, user_id, challenge_template_id, completed_at) VALUES (1, 1, 1, NULL);");
        $this->pdo->exec("UPDATE users SET running_challenge = 1 WHERE id = 1;");

        $curlHelper = $this->createMock(ICurlHelper::class);
        $curlHelper->method('makeBackendRequest')->willReturn(['success' => true, 'http_code' => 200]);

        ob_start();
        $handler = new ChallengeWorker(
            $this->databaseHelper,
            $curlHelper,
            $this->authHelper,
            false,
            $this->system,
            $this->env,
            $this->logger
        );

        $handler->run();
        $output = ob_get_clean();

        $this->assertStringContainsString("Successfully processed 1 expired challenges.", $output);
        $setCompletedStmt = $this->pdo->query("SELECT * FROM completed_challenges WHERE user_id = 1 AND challenge_template_id = 1");
        $completedChallenge = $setCompletedStmt->fetch(PDO::FETCH_ASSOC);
        $this->assertNotFalse($completedChallenge);
        $this->assertNotNull($completedChallenge['completed_at']);
    }

    public function testExpiredChallengeProcessingErrorThrowsException(): void
    {
        $this->requireMockDB();

        // Insert a challenge template
        $this->pdo->exec("
            INSERT INTO challenge_templates (id, name, difficulty, category)
            VALUES (1, 'Test Challenge', 'easy', 'web');
        ");

        // Insert an expired challenge
        $this->pdo->exec("INSERT INTO challenges (id, challenge_template_id, expires_at) VALUES (1, 1, CURRENT_TIMESTAMP - INTERVAL '1 hour');");
        $this->pdo->exec("INSERT INTO completed_challenges (id, user_id, challenge_template_id, completed_at) VALUES (1, 1, 1, NULL);");
        $this->pdo->exec("UPDATE users SET running_challenge = 1 WHERE id = 1;");

        $curlHelper = $this->createMock(ICurlHelper::class);
        $curlHelper->method('makeBackendRequest')->willReturn(['success' => false, 'http_code' => 500]);

        ob_start();
        $handler = new ChallengeWorker(
            $this->databaseHelper,
            $curlHelper,
            $this->authHelper,
            false,
            $this->system,
            $this->env,
            $this->logger
        );
        $handler->run();
        $output = ob_get_clean();

        $this->assertStringContainsString("Error processing challenges", $output);
    }

    public function testChallengeDeletionAfterExpiration(): void {
        $this->requireMockDB();

        // Insert a challenge template
        $this->pdo->exec("
            INSERT INTO challenge_templates (id, name, marked_for_deletion, difficulty, category)
            VALUES (1, 'Test Challenge', TRUE, 'easy', 'web');
        ");

        // Insert related data
        $this->pdo->exec("INSERT INTO disk_files (id, user_id, display_name, proxmox_filename) VALUES (1, 1, 'Test Disk', 'disk.vmdk');");
        $this->pdo->exec("INSERT INTO machine_templates (id, challenge_template_id, name, disk_file_id, ram_gb, cores) VALUES (1, 1, 'Machine 1', 1, 1, 1);");
        $this->pdo->exec("INSERT INTO network_templates (id, name, accessible, challenge_template_id) VALUES (1, 'net1', TRUE, 1);");
        $this->pdo->exec("INSERT INTO network_connection_templates (machine_template_id, network_template_id) VALUES (1, 1);");
        $this->pdo->exec("INSERT INTO domain_templates (machine_template_id, domain_name) VALUES (1, 'example.com');");
        $this->pdo->exec("INSERT INTO challenge_flags (id, challenge_template_id, flag, points) VALUES (1, 1, 'FLAG{test}', 100);");

        // Insert an expired challenge
        $this->pdo->exec("INSERT INTO challenges (id, challenge_template_id, expires_at) VALUES (1, 1, CURRENT_TIMESTAMP - INTERVAL '1 hour');");
        $this->pdo->exec("INSERT INTO completed_challenges (id, user_id, challenge_template_id, completed_at) VALUES (1, 1, 1, NULL);");
        $this->pdo->exec("UPDATE users SET running_challenge = 1 WHERE id = 1;");

        $curlHelper = $this->createMock(ICurlHelper::class);

        $mockStopChallengeMethod = function($url, $method, $headers, $data) {
            $this->pdo->exec("DELETE FROM challenges WHERE id = 1");
            return ['success' => true, 'http_code' => 200];
        };

        $curlHelper->method('makeBackendRequest')
            ->willReturnCallback(function($endpoint, $method, $headers, $body) use ($mockStopChallengeMethod) {
                if ($endpoint === '/stop-challenge' && $method === 'POST') {
                    return $mockStopChallengeMethod->call($this, $endpoint, $method, $headers, $body);
                }

                if ($endpoint === '/delete-machine-templates' && $method === 'POST') {
                    return ['success' => true, 'http_code' => 200];
                }

                throw new CustomException("Unexpected endpoint: $endpoint");
            });


        ob_start();
        $handler = new ChallengeWorker(
            $this->databaseHelper,
            $curlHelper,
            $this->authHelper,
            false,
            $this->system,
            $this->env,
            $this->logger
        );
        $handler->run();
        ob_get_clean();

        // Verify the challenge template and related data are deleted
        $tablesExpectedToBeEmpty = [
            'challenge_templates',
            'machine_templates',
            'network_templates',
            'network_connection_templates',
            'domain_templates',
            'challenge_flags'
        ];
        foreach ($tablesExpectedToBeEmpty as $table) {
            $stmt = $this->pdo->query("SELECT COUNT(*) FROM $table");
            $count = $stmt->fetchColumn();

            if($count > 0){
                $stmt = $this->pdo->query("SELECT * FROM $table");
                $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
            }

            $this->assertEquals(0, $count, "Table $table should be empty after deletion.");
        }
    }

    public function testChallengeDeletionBackendRequestErrorThrowsException(): void
    {
        $this->requireMockDB();

        // Insert a challenge template
        $this->pdo->exec("
            INSERT INTO challenge_templates (id, name, marked_for_deletion, difficulty, category)
            VALUES (1, 'Test Challenge', TRUE, 'easy', 'web');
        ");

        // Insert related data
        $this->pdo->exec("INSERT INTO disk_files (id, user_id, display_name, proxmox_filename) VALUES (1, 1, 'Test Disk', 'disk.vmdk');");
        $this->pdo->exec("INSERT INTO machine_templates (id, challenge_template_id, name, disk_file_id, ram_gb, cores) VALUES (1, 1, 'Machine 1', 1, 1, 1);");
        $this->pdo->exec("INSERT INTO network_templates (id, name, accessible, challenge_template_id) VALUES (1, 'net1', TRUE, 1);");
        $this->pdo->exec("INSERT INTO network_connection_templates (machine_template_id, network_template_id) VALUES (1, 1);");
        $this->pdo->exec("INSERT INTO domain_templates (machine_template_id, domain_name) VALUES (1, 'example.com');");
        $this->pdo->exec("INSERT INTO challenge_flags (id, challenge_template_id, flag, points) VALUES (1, 1, 'FLAG{test}', 100);");

        // Insert an expired challenge
        $this->pdo->exec("INSERT INTO challenges (id, challenge_template_id, expires_at) VALUES (1, 1, CURRENT_TIMESTAMP - INTERVAL '1 hour');");
        $this->pdo->exec("INSERT INTO completed_challenges (id, user_id, challenge_template_id, completed_at) VALUES (1, 1, 1, NULL);");
        $this->pdo->exec("UPDATE users SET running_challenge = 1 WHERE id = 1;");

        $curlHelper = $this->createMock(ICurlHelper::class);

        $mockStopChallengeMethod = function($url, $method, $headers, $data) {
            $this->pdo->exec("DELETE FROM challenges WHERE id = 1");
            return ['success' => true, 'http_code' => 200];
        };

        $curlHelper->method('makeBackendRequest')
            ->willReturnCallback(function ($endpoint, $method, $headers, $body) use ($mockStopChallengeMethod) {
                if ($endpoint === '/stop-challenge' && $method === 'POST') {
                    return $mockStopChallengeMethod->call($this, $endpoint, $method, $headers, $body);
                }

                if ($endpoint === '/delete-machine-templates' && $method === 'POST') {
                    return ['success' => false, 'http_code' => 500];
                }

                throw new CustomException("Unexpected endpoint: $endpoint");
            });

        ob_start();
        $handler = new ChallengeWorker(
            $this->databaseHelper,
            $curlHelper,
            $this->authHelper,
            false,
            $this->system,
            $this->env,
            $this->logger
        );
        $handler->run();
        $output = ob_get_clean();

        $this->assertStringContainsString("Error processing challenges", $output);
    }
}