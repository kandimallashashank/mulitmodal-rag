document.addEventListener('DOMContentLoaded', function() {
    const chatContainer = document.getElementById('chat-container');
    const followUpContainer = document.getElementById('follow-up-container');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const statusIndicator = document.getElementById('status-indicator');

    function updateStatus() {
        fetch('/status')
            .then(response => response.json())
            .then(data => {
                const statusBulb = document.getElementById('status-bulb');
                statusIndicator.title = data.status;
                statusBulb.style.backgroundColor = data.status.includes("Connected") ? "green" : "red";
            });
    }

    setInterval(updateStatus, 5000);

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
                
                setTimeout(() => {
                    addFollowUpQuestions(data.follow_up_questions);
                    scrollToBottom();
                }, 5000); // 5 seconds delay
                
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

    sendButton.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    function showSearchingIndicator() {
        const searchingElement = document.createElement('div');
        searchingElement.className = 'bot-message message searching';
        searchingElement.innerHTML = 'Searching<span></span><span></span><span></span>';
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

    function addMessage(sender, message) {
        const messageElement = document.createElement('div');
        messageElement.className = `${sender}-message message`;
        chatContainer.appendChild(messageElement);
    
        let index = 0;
    
        function typeNextChar() {
            if (index < message.length) {
                messageElement.textContent += message.charAt(index);
                index++;
                scrollToBottom();
                setTimeout(typeNextChar, 10);
            } else {
                scrollToBottom();
            }
        }
    
        typeNextChar();
    }

    function addSources(sources) {
        if (sources && sources.length > 0) {
            const sourcesElement = document.createElement('div');
            sourcesElement.className = 'sources';
            sourcesElement.innerHTML = '<strong>Sources:</strong><br>' + sources.map(source => 
                `${source.type} - ${source.document} (Page: ${source.page})`
            ).join('<br>');
            chatContainer.appendChild(sourcesElement);
            scrollToBottom();
        }
    }

    function addFollowUpQuestions(questions) {
        clearFollowUpQuestions();
        if (questions && questions.length > 0) {
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
            scrollToBottom();
        }
    }

    function clearFollowUpQuestions() {
        followUpContainer.innerHTML = '';
    }

    function scrollToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    // Ensure scroll to bottom when window is resized
    window.addEventListener('resize', scrollToBottom);

    // Ensure scroll to bottom when the page is fully loaded
    window.addEventListener('load', scrollToBottom);
});