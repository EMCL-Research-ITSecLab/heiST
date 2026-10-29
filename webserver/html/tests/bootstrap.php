<?php
// Tests may reuse an installed vendor cache through a symlink. Rebase application
// classes onto this checkout so tests cannot silently exercise another release.
define('PHPUNIT_RUNNING', true);
$sourceRoot = dirname(__DIR__);
$vendorRoot = realpath($sourceRoot . '/vendor');
$loader = require $sourceRoot . '/vendor/autoload.php';
$installedRoot = dirname($vendorRoot);
if (realpath($sourceRoot) !== realpath($installedRoot)) {
    $overrides = [];
    foreach ($loader->getClassMap() as $class => $file) {
        $file = realpath($file);
        if ($file !== false && str_starts_with($file, $installedRoot . '/')
            && !str_starts_with($file, $vendorRoot . '/')) {
            $localFile = $sourceRoot . substr($file, strlen($installedRoot));
            if (is_file($localFile)) {
                $overrides[$class] = $localFile;
            }
        }
    }
    $loader->addClassMap($overrides);
}
