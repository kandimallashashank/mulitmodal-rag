document.addEventListener('DOMContentLoaded', function() {
    const chatContainer = document.getElementById('chat-container');
    const followUpContainer = document.getElementById('follow-up-container');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const statusIndicator = document.getElementById('status-indicator');
    const leftPanel = document.querySelector('.left-panel');
    const rightPanel = document.querySelector('.right-panel');
    const resizer = document.getElementById('resizer');
    const splitScreen = document.querySelector('.split-screen');

    let isResizing = false;

    resizer.addEventListener('mousedown', initResize);
    document.addEventListener('mousemove', resize);
    document.addEventListener('mouseup', stopResize);

    function initResize(e) {
        isResizing = true;
        document.body.style.cursor = 'col-resize';
    }

    function resize(e) {
        if (!isResizing) return;
        const containerWidth = splitScreen.offsetWidth;
        const newLeftWidth = e.clientX - leftPanel.offsetLeft;
        const newRightWidth = containerWidth - newLeftWidth - resizer.offsetWidth;

        if (newLeftWidth > 300 && newRightWidth > 300) {
            const leftPercentage = (newLeftWidth / containerWidth) * 100;
            const rightPercentage = (newRightWidth / containerWidth) * 100;
            document.documentElement.style.setProperty('--chat-width', `${leftPercentage}%`);
            document.documentElement.style.setProperty('--pdf-width', `${rightPercentage}%`);
        }
    }

    function stopResize() {
        isResizing = false;
        document.body.style.cursor = 'default';
    }

    function updateStatus() {
        fetch('/status')
            .then(response => response.json())
            .then(data => {
                const statusBulb = document.getElementById('status-bulb');
                statusIndicator.title = data.status;
                statusBulb.style.backgroundColor = data.status.includes("Connected") ? "green" : "red";
            });
    }

    function sendMessage() {
        const question = userInput.value.trim();
        if (question) {
            addMessage('user', question);
            userInput.value = '';
            clearFollowUpQuestions();
            showSearchingIndicator();

            fetch('/ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question: question }),
            })
            .then(response => response.json())
            .then(data => {
                removeSearchingIndicator();
                addMessage('bot', data.response);
                addSources(data.sources);
                if (data.follow_up_questions) {
                    setTimeout(() => {
                        addFollowUpQuestions(data.follow_up_questions);
                    }, 1000);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                removeSearchingIndicator();
                addMessage('bot', 'Sorry, there was an error processing your request.');
            });
        }
    }

    function addMessage(sender, message) {
        const messageElement = document.createElement('div');
        messageElement.className = `${sender}-message message`;
        messageElement.textContent = message;
        chatContainer.appendChild(messageElement);
        scrollToBottom();
    }

    function showSearchingIndicator() {
        const searchingElement = document.createElement('div');
        searchingElement.className = 'bot-message message searching';
        searchingElement.textContent = 'Searching';
        searchingElement.id = 'searching-indicator';
        chatContainer.appendChild(searchingElement);
        scrollToBottom();
    }
    
    function removeSearchingIndicator() {
        const searchingElement = document.getElementById('searching-indicator');
        if (searchingElement) {
            searchingElement.remove();
        }
    }

    function addSources(sources) {
        console.log("Raw sources:", sources);  // Log the raw sources string
        if (sources && sources.trim() !== "") {
            const sourcesElement = document.createElement('div');
            sourcesElement.className = 'sources';
            sourcesElement.innerHTML = '<strong>Top 5 Relevant Sources:</strong><br>';
            
            const sourcesList = sources.split(/(?=\d+\.\s+(?:Text|Image Description) from)/).filter(Boolean);
            console.log("Split sources:", sourcesList);  // Log the split sources
            
            sourcesList.forEach((source) => {
                const sourceInfo = parseSourceInfo(source.trim());
                if (sourceInfo) {
                    const sourceLink = document.createElement('a');
                    sourceLink.href = '#';
                    sourceLink.textContent = `${sourceInfo.index}. ${sourceInfo.type} from ${sourceInfo.fileName} (Page ${sourceInfo.page})`;
                    sourceLink.onclick = function(e) {
                        e.preventDefault();
                        openSource(sourceInfo);
                    };
                    sourcesElement.appendChild(sourceLink);
                    sourcesElement.appendChild(document.createElement('br'));
                }
            });
            
            chatContainer.appendChild(sourcesElement);
            scrollToBottom();
        } else {
            console.log("No sources provided or empty sources string");  // Log if sources is empty
        }
    }

    function addFollowUpQuestions(questions) {
        clearFollowUpQuestions();
        if (followUpContainer && questions && questions.length > 0) {
            questions.forEach((question, index) => {
                const button = document.createElement('button');
                button.textContent = `${index + 1}. ${question}`;
                button.className = 'follow-up-button';
                button.addEventListener('click', () => {
                    userInput.value = question;
                    sendMessage();
                });
                followUpContainer.appendChild(button);
            });
        }
    }

    function clearFollowUpQuestions() {
        followUpContainer.innerHTML = '';
    }

    function scrollToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    function parseSourceInfo(source) {
        console.log("parseSourceInfo input:", source);

        const regex = /(\d+)\.\s+(Text|Image Description) from ((?:\.\/)?(?:data\/)?.*\.pdf) \(Page (\d+)(?:,\s*(.+))?\)/;
        const match = source.match(regex);

        if (match) {
            const result = {
                index: match[1],
                type: match[2],
                fileName: match[3].replace(/^\.\//, '').replace(/^data\//, ''),
                page: match[4],
                additional: match[5] || ''
            };
            console.log("parseSourceInfo output:", result);
            return result;
        } else {
            console.log("parseSourceInfo failed to match regex");
            return null;
        }
    }

    function openSource(sourceInfo) {
        console.log("openSource input:", sourceInfo);

        if (sourceInfo) {
            const viewerContainer = document.getElementById('viewer-container');
            if (!viewerContainer) {
                console.log("Viewer container not found");
                return;
            }
            
            viewerContainer.innerHTML = '';

            // const url = `/data/${encodeURIComponent(sourceInfo.fileName)}#page=${sourceInfo.page}`;
            const sanitizedFileName = sourceInfo.fileName.replace(/\\/g, '/');
            const url = `/data/${encodeURIComponent(sanitizedFileName)}#page=${sourceInfo.page}`;
            console.log("PDF URL:", url);

            const pdfViewer = document.createElement('iframe');
            pdfViewer.id = 'pdf-viewer';
            pdfViewer.src = url;
            
            const closeButton = document.createElement('button');
            closeButton.id = 'close-pdf';
            closeButton.textContent = 'Close';
            closeButton.onclick = closePDFViewer;
            
            viewerContainer.appendChild(closeButton);
            viewerContainer.appendChild(pdfViewer);
            
            openPDFViewer();
        } else {
            console.log("openSource called with null or undefined sourceInfo");
        }
    }

    function openPDFViewer() {
        document.documentElement.style.setProperty('--chat-width', '50%');
        document.documentElement.style.setProperty('--pdf-width', '50%');
        rightPanel.style.display = 'flex';
        resizer.style.display = 'block';
    }

    function closePDFViewer() {
        document.documentElement.style.setProperty('--chat-width', '100%');
        document.documentElement.style.setProperty('--pdf-width', '0%');
        setTimeout(() => {
            rightPanel.style.display = 'none';
            resizer.style.display = 'none';
        }, 300); // Wait for transition to complete
    }

    function adjustPanelSizes() {
        const totalWidth = splitScreen.offsetWidth;
        if (rightPanel.style.display !== 'none') {
            document.documentElement.style.setProperty('--chat-width', '50%');
            document.documentElement.style.setProperty('--pdf-width', '50%');
        } else {
            document.documentElement.style.setProperty('--chat-width', '100%');
            document.documentElement.style.setProperty('--pdf-width', '0%');
        }
    }

    sendButton.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    window.addEventListener('resize', adjustPanelSizes);

    updateStatus();
    setInterval(updateStatus, 5000);

    // Initially hide the right panel and resizer
    rightPanel.style.display = 'none';
    resizer.style.display = 'none';
    document.documentElement.style.setProperty('--chat-width', '100%');
    document.documentElement.style.setProperty('--pdf-width', '0%');
});