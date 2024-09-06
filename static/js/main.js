document.addEventListener('DOMContentLoaded', function() {
    const chatContainer = document.getElementById('chat-container');
    const followUpContainer = document.getElementById('follow-up-container');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const statusIndicator = document.getElementById('status-indicator');
    const leftPanel = document.querySelector('.left-panel');
    const rightPanel = document.querySelector('.right-panel');
    const resizer = document.getElementById('resizer');

    // Resizer functionality
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

        const containerWidth = document.querySelector('.split-screen').offsetWidth;
        const newLeftWidth = e.clientX - leftPanel.offsetLeft;
        const newRightWidth = containerWidth - newLeftWidth - resizer.offsetWidth;

        if (newLeftWidth > 300 && newRightWidth > 300) {
            leftPanel.style.width = `${newLeftWidth}px`;
            rightPanel.style.width = `${newRightWidth}px`;
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
            sendButton.disabled = true;
            userInput.disabled = true;

            addMessage('user', question);
            userInput.value = '';
            clearFollowUpQuestions();

            showSearchingIndicator();

            fetch('/ask', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
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
                        scrollToBottom();
                    }, 1000);
                }
                
                sendButton.disabled = false;
                userInput.disabled = false;
                userInput.focus();
            })
            .catch(error => {
                console.error('Error:', error);
                removeSearchingIndicator();
                addMessage('bot', 'Sorry, there was an error processing your request.');
                sendButton.disabled = false;
                userInput.disabled = false;
                userInput.focus();
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
        if (sources && sources.trim() !== "") {
            const sourcesElement = document.createElement('div');
            sourcesElement.className = 'sources';
            sourcesElement.innerHTML = '<strong>Sources:</strong><br>';
            
            const sourcesList = sources.split(/(?=\d+\.\s+(?:Text|Image) from)/).filter(Boolean);
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
        }
    }

    function addFollowUpQuestions(questions) {
        clearFollowUpQuestions();
        if (followUpContainer && questions && questions.length > 0) {
            questions.slice(0, 2).forEach((question, index) => {
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
        const regex = /(\d+)\.\s+(Text|Image Description) from ((?:\.\/)?(?:data\/)?.*\.pdf) \(Page (\d+)(?:,\s*(.+))?\)/;
        const match = source.match(regex);
        if (match) {
            return {
                index: match[1],
                type: match[2],
                fileName: match[3].replace(/^\.\//, '').replace(/^data\//, ''),
                page: match[4],
                additional: match[5] || ''
            };
        }
        return null;
    }

    async function openSourceWithTest(sourceInfo) {
        console.log("Opening source:", sourceInfo); // Debugging log
        const url = `/data/${encodeURIComponent(sourceInfo.fileName)}`;
        const isAccessible = await testPDFAccess(url);
        if (isAccessible) {
            openSource(sourceInfo);
        } else {
            const viewerContainer = document.getElementById('viewer-container');
            if (viewerContainer) {
                viewerContainer.innerHTML = `
                    <p>Error: PDF file is not accessible. Please check the file path and server configuration.</p>
                    <p>Attempted URL: ${url}</p>
                `;
            }
            addFallbackLink(sourceInfo);
        }
    }

    function testPDFAccess(url) {
        return fetch(url, { method: 'HEAD' })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return true;
            })
            .catch(e => {
                console.error("PDF is not accessible:", e);
                return false;
            });
    }

    function openSource(sourceInfo) {
        if (sourceInfo) {
            const viewerContainer = document.getElementById('viewer-container');
            if (!viewerContainer) return;
            
            viewerContainer.innerHTML = '';
    
            const url = `/data/${sourceInfo.fileName}#page=${sourceInfo.page}`;
    
            const pdfViewer = document.createElement('iframe');
            pdfViewer.id = 'pdf-viewer';
            pdfViewer.src = url;
            pdfViewer.style.width = '100%';
            pdfViewer.style.height = '100%';
            pdfViewer.style.border = 'none';
            
            pdfViewer.onload = () => {
                console.log("PDF iframe loaded");
                openPDFPanel();
            };
        
            pdfViewer.onerror = (error) => {
                console.error("Error loading PDF in iframe:", error);
                viewerContainer.innerHTML = `
                    <p>Error loading PDF in iframe. Please try the direct link below:</p>
                `;
                addDirectLink(url);
                openPDFPanel();
            };
            
            viewerContainer.appendChild(pdfViewer);
            
            // Add a fallback link in case the iframe doesn't load properly
            addDirectLink(url);
        }
    }

    function addDirectLink(url) {
        const viewerContainer = document.getElementById('viewer-container');
        const directLink = document.createElement('a');
        directLink.href = url;
        directLink.target = "_blank";
        directLink.textContent = "Open PDF directly";
        directLink.style.display = "block";
        directLink.style.marginTop = "10px";
        viewerContainer.appendChild(directLink);
    }

    function addFallbackLink(sourceInfo) {
        const viewerContainer = document.getElementById('viewer-container');
        const fallbackLink = document.createElement('a');
        fallbackLink.href = `/data/${sourceInfo.fileName}`;
        fallbackLink.target = "_blank";
        fallbackLink.textContent = "Open PDF in new tab";
        fallbackLink.style.display = "block";
        fallbackLink.style.marginTop = "10px";
        viewerContainer.appendChild(fallbackLink);
    }

    // Event listeners
    sendButton.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    // Ensure proper sizing on window resize
    window.addEventListener('resize', () => {
        if (rightPanel.querySelector('#pdf-viewer')) {
            rightPanel.querySelector('#pdf-viewer').style.height = `${rightPanel.clientHeight}px`;
        }
    });

    // Initialize
    updateStatus();
    setInterval(updateStatus, 5000);
});