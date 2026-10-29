<?php
declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

class MockLogger implements ILogger
{
    public array $records = [];
    public function logInfo($message): void
    {
        $this->records[] = ['level' => 'info', 'message' => $message];
    }

    public function logError($message): void
    {
        $this->records[] = ['level' => 'error', 'message' => $message];
    }

    public function logDebug($message): void
    {
        $this->records[] = ['level' => 'debug', 'message' => $message];
    }

    public function logWarning($message): void
    {
        $this->records[] = ['level' => 'warning', 'message' => $message];
    }

    public function anonymizeIp(string $ip): string
    {
        return $ip;
    }
}