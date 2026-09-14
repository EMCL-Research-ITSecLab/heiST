import {messageManager, apiClient} from './utils.js';

function openOSModal() {
    return new Promise((resolve) => {
        const overlay = document.getElementById('os-modal-overlay');
        const nextBtn = document.getElementById('os-next-btn');
        const cancelBtn = document.getElementById('os-cancel-btn');
        const osOptions = overlay.querySelectorAll('.os-option');

        osOptions.forEach(o => o.classList.remove('selected'));
        nextBtn.disabled = true;
        overlay.classList.add('active');

        function onOptionClick() {
            osOptions.forEach(o => o.classList.remove('selected'));
            this.classList.add('selected');
            nextBtn.disabled = false;
        }

        function cleanup() {
            overlay.classList.remove('active');
            nextBtn.removeEventListener('click', onNext);
            cancelBtn.removeEventListener('click', onCancel);
            overlay.removeEventListener('click', onBackdrop);
            osOptions.forEach(o => o.removeEventListener('click', onOptionClick));
        }

        function onNext() {
            const selected = overlay.querySelector('.os-option.selected');
            cleanup();
            resolve(selected ? selected.dataset.os : null);
        }

        function onCancel() {
            cleanup();
            resolve(null);
        }

        function onBackdrop(e) {
            if (e.target === overlay) {
                cleanup();
                resolve(null);
            }
        }

        osOptions.forEach(o => o.addEventListener('click', onOptionClick));
        nextBtn.addEventListener('click', onNext);
        cancelBtn.addEventListener('click', onCancel);
        overlay.addEventListener('click', onBackdrop);
    });
}

class FileUploader {
    constructor() {
        this.domElements = {
            dropzone: document.getElementById('upload-dropzone'),
            fileInput: document.getElementById('file-input'),
            browseBtn: document.getElementById('browse-btn'),
            uploadBtn: document.getElementById('upload-btn'),
            cancelBtn: document.getElementById('cancel-btn'),
            fileName: document.getElementById('file-name'),
            fileSize: document.getElementById('file-size'),
            ovaList: document.getElementById('ova-list'),
            searchInput: document.getElementById('search-ovas'),
            progressContainer: document.getElementById('upload-progress-container'),
            progressText: document.getElementById('upload-progress-text'),
            progressBar: document.getElementById('upload-progress-bar')
        };

        this.state = {
            selectedFile: null,
            uploadInProgress: false,
            currentUploadId: null
        };

        this.loadConfig().then(() => {
            this.init();
        });
    }

    init() {
        this.resetProgressUI();
        this.setupEventListeners();
        this.fetchUserOVAs();
    }

    async loadConfig() {
        try {
            const response = await fetch('/config/general.config.json');
            const config = await response.json();
            this.config = config.upload;

        } catch (error) {
            console.error('Failed to load config:', error);
        }
    }

    setupEventListeners() {
        this.domElements.browseBtn.addEventListener('click', () => this.domElements.fileInput.click());
        this.domElements.fileInput.addEventListener('change', (e) => this.handleFileSelect(e));
        this.domElements.uploadBtn.addEventListener('click', () => this.handleUpload());
        this.domElements.cancelBtn.addEventListener('click', () => this.cancelUpload());
        this.domElements.searchInput.addEventListener('input', () => this.filterOVAs());


        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            this.domElements.dropzone.addEventListener(eventName, this.preventDefaults, false);
        });

        ['dragenter', 'dragover'].forEach(eventName => {
            this.domElements.dropzone.addEventListener(eventName, this.highlightDropzone, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            this.domElements.dropzone.addEventListener(eventName, this.unhighlightDropzone, false);
        });

        this.domElements.dropzone.addEventListener('drop', (e) => this.handleDrop(e), false);
    }

    preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    highlightDropzone() {
        this.domElements.dropzone.classList.add('drag-over');
    }

    unhighlightDropzone() {
        this.domElements.dropzone.classList.remove('drag-over');
    }

    handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length) {
            this.handleFile(files[0]);
        }
    }

    handleFileSelect(e) {
        if (e.target.files.length) {
            this.handleFile(e.target.files[0]);
        }
    }

    handleFile(file) {
        if (this.state.uploadInProgress) {
            messageManager.showError('Please wait for current upload to finish');
            return;
        }

        if (!this.isValidFile(file)) {
            return;
        }

        this.state.selectedFile = file;
        this.domElements.fileName.textContent = file.name;
        this.domElements.fileSize.textContent = this.formatFileSize(file.size);
        this.domElements.uploadBtn.disabled = false;
    }

    isValidFile(file) {
        const isValidExtension = this.config.VALID_FILE_TYPES.some(ext =>
            file.name.toLowerCase().endsWith(ext)
        );

        if (!isValidExtension) {
            messageManager.showError('Please select an OVA or OVF file');
            return false;
        }

        if (file.size > this.config.MAX_FILE_SIZE) {
            messageManager.showError('File size exceeds maximum limit of 10GB');
            return false;
        }

        return true;
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    async handleUpload() {
        if (!this.state.selectedFile) return;

        const guestOS = await openOSModal();
        if (!guestOS) return;

        this.state.guestOS = guestOS;

        const useChunkedUpload = this.state.selectedFile.size > this.config.CHUNK_UPLOAD_THRESHOLD;

        try {
            if (useChunkedUpload) {
                await this.handleChunkedUpload(this.config.CHUNK_SIZE);
            } else {
                await this.handleDirectUpload();
            }
        } catch (error) {
            console.error('Upload error:', error);
            messageManager.showError('Error uploading file: ' + (error.message || 'Unknown error'));
        }
    }

    async handleDirectUpload() {
        const formData = new FormData();
        formData.append('ova_file', this.state.selectedFile);
        formData.append('guest_os', this.state.guestOS);

        this.setUploadingState(true);

        try {
            const data = await apiClient.post('../backend/upload-diskfile.php', formData);

            if (data?.success) {
                messageManager.showSuccess('File uploaded successfully!');
                this.resetForm();
                this.fetchUserOVAs();
            }
        } finally {
            this.setUploadingState(false);
        }
    }

    async handleChunkedUpload(chunkSize) {
        const totalChunks = Math.ceil(this.state.selectedFile.size / chunkSize);
        this.state.uploadInProgress = true;
        this.setUploadingState(true, true);

        try {

            const initData = await apiClient.post('../backend/upload-diskfile.php', {
                phase: 'init',
                uploadId: 'temp_' + Date.now(),
                fileName: this.state.selectedFile.name,
                fileSize: this.state.selectedFile.size,
                totalChunks: totalChunks,
                guest_os: this.state.guestOS
            });

            if(initData?.success) {
                this.state.currentUploadId = initData.uploadId;

                for (let chunkIndex = 0; chunkIndex < totalChunks; chunkIndex++) {
                    if (!this.state.uploadInProgress) throw new Error('Upload cancelled');

                    const start = chunkIndex * chunkSize;
                    const end = Math.min(start + chunkSize, this.state.selectedFile.size);
                    const chunk = this.state.selectedFile.slice(start, end);

                    const formData = new FormData();
                    formData.append('chunk', chunk);
                    formData.append('uploadId', this.state.currentUploadId);
                    formData.append('chunkIndex', chunkIndex);
                    formData.append('phase', 'chunk');

                    await apiClient.post('../backend/upload-diskfile.php', formData);


                    const progress = Math.round(((chunkIndex + 1) / totalChunks) * 100);
                    this.updateProgress(progress);
                }

                this.domElements.cancelBtn.disabled = true;

                const finalizeResponse = await apiClient.post('../backend/upload-diskfile.php', {
                    phase: 'finalize',
                    uploadId: this.state.currentUploadId
                });

                if (finalizeResponse?.success) {
                    messageManager.showSuccess('File uploaded successfully!');
                }

                this.resetForm();
                this.fetchUserOVAs();
            }
        } finally {
            this.state.uploadInProgress = false;
            this.state.currentUploadId = null;
            this.setUploadingState(false);
        }
    }

    setUploadingState(isUploading, showCancel = false) {
        this.domElements.uploadBtn.disabled = isUploading;
        this.domElements.uploadBtn.innerHTML = isUploading
            ? '<span class="loading-spinner"></span> Uploading...'
            : 'Upload OVA';
        this.domElements.cancelBtn.style.display = showCancel ? 'inline-block' : 'none';
        this.domElements.cancelBtn.disabled = false;

        if (!isUploading) {
            this.resetProgressUI();
        }
    }

    updateProgress(percent) {
        this.domElements.progressContainer.style.display = 'flex';
        this.domElements.progressBar.style.display = 'block';
        this.domElements.progressText.style.display = 'block';
        this.domElements.progressBar.style.width = `${percent}%`;
        this.domElements.progressText.textContent = `${percent}%`;
    }

    resetProgressUI() {
        this.domElements.progressBar.style.width = '0%';
        this.domElements.progressText.textContent = '';
        this.domElements.progressBar.style.display = 'none';
        this.domElements.progressText.style.display = 'none';
        this.domElements.progressContainer.style.display = 'none';
    }

    async cancelUpload() {
        if (this.state.uploadInProgress) {
            if (confirm('Are you sure you want to cancel the upload?')) {
                try {
                    if (this.state.currentUploadId) {
                        await apiClient.post('../backend/upload-diskfile.php', {
                            phase: 'cancel',
                            uploadId: this.state.currentUploadId
                        }).catch(error => {
                            console.error('Error during cancel:', error);
                        });
                    }

                    this.state.uploadInProgress = false;
                    this.setUploadingState(false);
                    this.domElements.progressText.textContent = 'Cancelled';
                    messageManager.showSuccess('Upload cancelled');
                } catch (error) {
                    console.error('Cancel error:', error);
                    this.state.uploadInProgress = false;
                    this.setUploadingState(false);
                    messageManager.showError('Error while cancelling Upload: ' + (error.message || 'Unknown error'));
                }
            }
        } else {
            this.resetForm();
        }
    }

    resetForm() {
        this.state.selectedFile = null;
        this.domElements.fileInput.value = '';
        this.domElements.fileName.textContent = 'No file selected';
        this.domElements.fileSize.textContent = '';
        this.domElements.uploadBtn.disabled = true;
        this.resetProgressUI();
    }

    async fetchUserOVAs() {
        try {
            const data = await apiClient.get('../backend/upload-diskfile.php?action=list');

            if (data?.success) {
                this.renderOVAList(data.ovas);
            } else {
                throw new Error(data?.message || 'Failed to fetch OVAs');
            }
        } catch (error) {
            console.error('Error fetching OVAs:', error);
            this.showOVAError(error.message);
        }
    }

    renderOVAList(ovas) {
        if (ovas.length === 0) {
            this.showEmptyState();
            return;
        }

        this.domElements.ovaList.innerHTML = ovas.map(ova => this.createOVAItem(ova)).join('');
        this.setupOVAItemEventListeners();
    }

    createOVAItem(ova) {
        return `
            <div class="ova-item" data-id="${ova.id}">
                <div class="ova-header">
                    <div class="ova-name">${ova.display_name}</div>
                    <div class="ova-date">${new Date(ova.upload_date).toLocaleDateString()}</div>
                </div>
                <div class="ova-details">
                    <div class="ova-guest-os">
                        ${ova.guest_os && ova.guest_os.toLowerCase() === 'windows' ? '<i class="fa-brands fa-windows"></i> windows' : '<i class="fa-brands fa-linux"></i> linux'}
                    </div>
                </div>
                <div class="ova-actions">
                    <button class="button button-primary use-ova-btn">Use This OVA</button>
                    <button class="button button-danger delete-ova-btn"><i class="fa-solid fa-trash"></i></button>
                </div>
            </div>
        `;
    }

    setupOVAItemEventListeners() {
        document.querySelectorAll('.use-ova-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const ovaId = btn.closest('.ova-item').getAttribute('data-id');
                window.location.href = `/create-ctf?ova=${ovaId}`;
            });
        });

        document.querySelectorAll('.delete-ova-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const ovaId = btn.closest('.ova-item').getAttribute('data-id');
                const ovaName = btn.closest('.ova-item').querySelector('.ova-name').textContent;

                if (confirm(`Are you sure you want to delete "${ovaName}"?`)) {
                    try {
                        const data = await apiClient.delete('../backend/upload-diskfile.php?action=delete', {
                            data: {ova_id: ovaId}
                        });

                        if (data?.success) {
                            this.fetchUserOVAs();
                        }
                    } catch (error) {
                        console.error('Delete error:', error);
                        messageManager.showError('Error deleting OVA: ' + (error.message || 'Unknown error'));
                    }
                }
            });
        });
    }

    showEmptyState() {
        this.domElements.ovaList.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-box-open"></i>
                <p>You haven't uploaded any OVAs yet</p>
            </div>
        `;
    }

    showOVAError(message) {
        this.domElements.ovaList.innerHTML = `
            <div class="error-state">
                <i class="fa-solid fa-exclamation-triangle"></i>
                <p>Error loading OVAs: ${message}</p>
            </div>
        `;
    }

    filterOVAs() {
        const searchTerm = this.domElements.searchInput.value.toLowerCase();
        const ovaItems = document.querySelectorAll('.ova-item');

        ovaItems.forEach(item => {
            const name = item.querySelector('.ova-name').textContent.toLowerCase();
            item.style.display = name.includes(searchTerm) ? 'block' : 'none';
        });
    }
}


if (typeof window !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
        new FileUploader();
    });
}

export default FileUploader;