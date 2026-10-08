<?php
declare(strict_types=1);
require_once __DIR__ . '/../vendor/autoload.php';

$securityHelper = new SecurityHelper();
$securityHelper->initSecureSession();

$databaseHelper = new DatabaseHelper();
$pdo = $databaseHelper->getPDO();

if (!$securityHelper->validateSession() || !$securityHelper->validateAdminAccess($pdo)) {
    header('Location: /404');
    exit();
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Create CTF - heiST</title>
    <link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg">
    <link rel="stylesheet" href="../assets/css/base.css">
    <link rel="stylesheet" href="../assets/css/create-ctf.css">
</head>
<body>
<?php include($_SERVER['DOCUMENT_ROOT'] . '/partials/header.html'); ?>
<main class="create-ctf-container">
    <div class="view-mode-toggle">
        <span class="toggle-label"><i class="fa-solid fa-mouse-pointer"></i> Manual</span>
        <div class="toggle-switch" id="view-mode-toggle">
            <div class="toggle-slider"></div>
        </div>
        <span class="toggle-label"><i class="fa-solid fa-file-code"></i> YAML</span>
    </div>

    <div class="yaml-upload-view" id="yaml-upload-view">
        <div class="yaml-upload-container">
            <div class="yaml-upload-header">
                <h2><i class="fa-solid fa-file-code"></i> Upload CTF Configuration</h2>
                <p>Upload a YAML file to automatically configure your CTF challenge</p>
            </div>

            <div class="yaml-drop-zone" id="yaml-drop-zone">
                <i class="fa-solid fa-cloud-arrow-up"></i>
                <p>Drag & drop your YAML file here</p>
                <small>or click to browse</small>
            </div>

            <input type="file" id="yaml-file-input" accept=".yaml,.yml" style="display: none;">

            <div class="yaml-file-info" id="yaml-file-info">
                <h4><i class="fa-solid fa-file-circle-check"></i> File Loaded</h4>
                <p><strong>Filename:</strong> <span id="yaml-filename"></span></p>
                <p><strong>Size:</strong> <span id="yaml-filesize"></span></p>
            </div>

            <div class="yaml-actions">
                <button class="button button-secondary" id="yaml-clear-btn" style="display: none;">
                    <i class="fa-solid fa-xmark"></i> Clear
                </button>
                <button class="button button-primary" id="yaml-import-btn" style="display: none;">
                    <i class="fa-solid fa-file-import"></i> Import Configuration
                </button>
            </div>

            <div class="yaml-example">
                <h3><i class="fa-solid fa-code"></i> YAML Format Example</h3>
                <pre>ctf:
  name: "My CTF Challenge"
  description: "Challenge description"
  category: "web"
  difficulty: "medium"
  solution: "you need to do an sql injection with '1 OR 1 = 1'"
  hint: "look into sql attacks"
  is_active: true

  vms:
    web-server:
      ova_name: "Ubuntu 20.04"
      cores: 2
      ram_gb: 4
      domain_name: "web.challenge.local"
      ad_role: "none"

    database:
      ova_name: "Ubuntu 20.04"
      cores: 1
      ram_gb: 2
      domain_name: "db.challenge.local"

  subnets:
    public:
      accessible: true
      dmz: true
      attached_vms: ["web-server", "database"]

    internal:
      accessible: false
      dmz: true
      attached_vms:
        - "web-server"
        - "database"

  flags:
    0:
      flag: "CTF{example_flag}"
      points: 100
      order_index: 0
      user_specific: false

    1:
      flag: "secret"
      points: 200
      order_index: 1
      user_specific: true
      vm_name: "web-server"

  hints:
    0:
      hint_text: "Check the logs"
      unlock_points: 50
      order_index: 0</pre>

                <div class="yaml-download-template">
                    <a href="#" id="yaml-download-template">
                        <i class="fa-solid fa-download"></i> Download Template
                    </a>
                </div>
            </div>
        </div>
    </div>

    <div class="manual-creation-view" id="manual-creation-view">
        <div class="visual-layout">
            <section class="general-info-tabbed">
                <div class="tab-headers">
                    <div id="tab-general" class="tab-header active">General Information</div>
                    <div id="tab-advanced" class="tab-header">Advanced Options</div>
                </div>
                <div id="tab-general-content" class="tab-content">
                    <div class="general-info-container">
                        <div class="form-group ctf-input-name">
                            <label for="ctf-name">CTF Name</label>
                            <input type="text" id="ctf-name" name="ctf-name" required>
                        </div>
                        <div class="description-tag-group">
                            <div class="form-group">
                                <label for="ctf-description">Description</label>
                                <textarea id="ctf-description" name="ctf-description" rows="4" required></textarea>
                            </div>
                            <div class="tag-group">
                                <div class="form-group a dropdown">
                                    <label for="ctf-category">Category</label>
                                    <select id="ctf-category" name="ctf-category" required>
                                        <option value="web">Web</option>
                                        <option value="crypto">Crypto</option>
                                        <option value="forensics">Forensics</option>
                                        <option value="reverse">Reverse Engineering</option>
                                        <option value="pwn">Pwn</option>
                                        <option value="misc">Miscellaneous</option>
                                    </select>
                                </div>
                                <div class="form-group b dropdown">
                                    <label for="ctf-difficulty">Difficulty</label>
                                    <select id="ctf-difficulty" name="ctf-difficulty" required>
                                        <option value="easy">Easy</option>
                                        <option value="medium">Medium</option>
                                        <option value="hard">Hard</option>
                                    </select>
                                </div>
                            </div>
                        </div>

                    </div>
                    <div class="general-info-image-container" id="image-upload-container">
                        <img src="/assets/images/ctf-default.png" alt="CTF Challenge Image" id="ctf-image-preview" class="ctf-image-preview">
                        <div class="image-upload-overlay">Click to upload image<br><span class="hint">(Default shown)</span>
                        </div>
                    </div>
                </div>

                <div id="tab-advanced-content" class="tab-content hidden">
                    <div class="general-info-container">
                        <div class="form-group">
                            <label for="ctf-hint">Hint</label>
                            <textarea id="ctf-hint" name="ctf-hint" rows="2"></textarea>
                        </div>
                        <div class="form-group">
                            <label for="ctf-solution">Solution</label>
                            <textarea id="ctf-solution" name="ctf-solution" rows="4"></textarea>
                        </div>
                    </div>
                </div>
            </section>
            <section class="visual-representation">
                <h2>Visual Representation</h2>
                <div class="visual-canvas">
                    <div id="subnet-regions"></div>
                </div>
                <div id="vm-icons" class="vm-list"></div>
            </section>
        </div>
        <section class="tabbed-input-area">
            <div class="tab-buttons">
                <button type="button" id="tab-vm" class="tab-button active">
                    <i class="fa-solid fa-desktop"></i> Add Virtual Machine
                </button>
                <button type="button" id="tab-subnet" class="tab-button">
                    <i class="fa-solid fa-network-wired"></i> Add Subnet
                </button>
                <button type="button" id="tab-flag" class="tab-button">
                    <i class="fa-solid fa-flag"></i> Add Flag
                </button>
                <button type="button" id="tab-hint" class="tab-button">
                    <i class="fa-solid fa-lightbulb"></i> Add Hint
                </button>
            </div>
            <div id="vm-input" class="input-section active">
                <form id="vm-form">
                    <div class="form-group">
                        <label for="vm-name">Name</label>
                        <input type="text" id="vm-name" name="vm-name" required>
                    </div>
                    <div class="form-group">
                        <label for="vm-ova">OVA Template</label>
                        <div class="ova-select dropdown">
                            <select id="vm-ova" class="ova-list" name="vm-ova" required>
                                <option value="">-- Select OVA Template --</option>
                                <!-- This will be populated by JavaScript -->
                            </select>
                            <a href="/upload-diskfile" class="button button-secondary upload-btn" id="vm-ova-apply">upload
                                new</a>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="vm-cores">Cores</label>
                        <input type="number" id="vm-cores" name="vm-cores" min="1" required>
                        <div class="number-controls">
                            <button type="button" class="number-btn">▲</button>
                            <button type="button" class="number-btn">▼</button>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="vm-ram">RAM (GB)</label>
                        <input type="number" id="vm-ram" name="vm-ram" min="1" required>
                        <div class="number-controls">
                            <button type="button" class="number-btn">▲</button>
                            <button type="button" class="number-btn">▼</button>
                        </div>
                    </div>
                    <div class="form-group">
                        <label for="vm-ip">Domain</label>
                        <input type="text" id="vm-ip" name="vm-ip" required>
                    </div>
                    <div class="form-group">
                        <label for="vm-ad-role">Active Directory Role</label>
                        <select id="vm-ad-role" name="vm-ad-role">
                            <option value="none">None</option>
                            <option value="dc">Domain Controller</option>
                            <option value="member">Domain Member</option>
                        </select>
                        <span class="ad-role-hint" id="ad-role-hint"></span>
                    </div>
                    <button type="submit" class="button button-primary">Add VM</button>
                </form>
            </div>
            <div id="subnet-input" class="input-section">
                <form id="subnet-form">
                    <div class="form-group">
                        <label for="subnet-name">Name</label>
                        <input type="text" id="subnet-name" name="subnet-name" required>
                    </div>
                    <div class="form-group slider-container">
                        <label class="option-switch">
                            <input type="checkbox" id="subnet-dmz" name="subnet-dmz">
                            <span class="option-slider round"></span>
                        </label>
                        <span class="option-switch-label">Internet (Outbound Only)</span>
                    </div>
                    <div class="form-group slider-container">
                        <label class="option-switch">
                            <input type="checkbox" id="subnet-accessible" name="subnet-accessible">
                            <span class="option-slider round"></span>
                        </label>
                        <span class="option-switch-label">Public-Facing (Contestant-Reachable)</span>
                    </div>
                    <div class="form-group">
                        <label>Attached VMs</label>
                        <div id="vm-checkbox-list" class="vm-checkbox-list">
                            <!-- This will be populated by JavaScript -->
                        </div>
                    </div>
                    <button type="submit" class="button button-primary">Add Subnet</button>
                </form>
            </div>
            <div id="flag-input" class="input-section">
                <form id="flag-form">
                    <div class="form-group">
                        <label for="flag-text">Flag</label>
                        <input type="text" id="flag-text" name="flag-text" required>
                    </div>
                    <div class="form-group">
                        <label for="flag-description">Description (This is just for you)</label>
                        <textarea id="flag-description" name="flag-description" rows="3"></textarea>
                    </div>
                    <div class="form-group">
                        <label for="flag-points">Points</label>
                        <input type="number" id="flag-points" name="flag-points" min="1" required>
                    </div>
                    <div class="form-group">
                        <label for="flag-order">Order Index</label>
                        <input type="number" id="flag-order" name="flag-order" min="0" value="0">
                    </div>
                    <div class="form-group slider-container">
                        <label class="option-switch">
                            <input type="checkbox" id="flag-userspecific" name="flag-userspecific">
                            <span class="option-slider round"></span>
                        </label>
                        <span class="option-switch-label">Userspecific Flag</span>
                    </div>
                    <div class="flag-vm-dropdown-container" style="display: none;">
                        <label for="flag-vm">Assigned VM *</label>
                        <select id="flag-vm" name="flag-vm">
                            <option value="">-- Select VM --</option>
                        </select>
                    </div>
                    <button type="submit" class="button button-primary">Add Flag</button>
                </form>
                <div class="flags-list" id="flags-list">
                    <!-- This will be populated by JavaScript -->
                </div>
            </div>
            <div id="hint-input" class="input-section">
                <form id="hint-form">
                    <div class="form-group">
                        <label for="hint-text">Hint Text</label>
                        <textarea id="hint-text" name="hint-text" rows="3" required></textarea>
                    </div>
                    <div class="form-group">
                        <label for="hint-points">Unlock Points</label>
                        <input type="number" id="hint-points" name="hint-points" min="0" value="0">
                    </div>
                    <div class="form-group">
                        <label for="hint-order">Order Index</label>
                        <input type="number" id="hint-order" name="hint-order" min="0" value="0">
                    </div>
                    <button type="submit" class="button button-primary">Add Hint</button>
                </form>
                <div class="hints-list" id="hints-list">
                    <!-- This will be populated by JavaScript -->
                </div>
            </div>
        </section>
        <div class="submit-section">
            <div class="status-toggle-container">
                <label class="option-switch">
                    <input type="checkbox" checked id="ctf-is-active" name="ctf-is-active">
                    <span class="option-slider round"></span>
                </label>
                <span class="option-switch-label">Active after Creation</span>
                <small class="creator-note">(You can always deploy as creator)</small>
            </div>
            <button id="submit-ctf" class="button button-primary">Create CTF Challenge</button>
        </div>
    </div>

</main>
<?php include($_SERVER['DOCUMENT_ROOT'] . '/partials/footer.html'); ?>

<script type="module" src="../assets/js/theme-toggle.js"></script>
<script type="module" src="../assets/js/create-ctf.js"></script>
</body>
</html>