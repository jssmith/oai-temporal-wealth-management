import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import { API_CONFIGS, DEFAULT_API_MODE, getApiConfig } from './config';

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const [isChatActive, setIsChatActive] = useState(false);
  const chatWindowRef = useRef(null);
  const defaultHeaderText = 'Chat session started.';
  const workflow_id_prefix = 'oai-temporal-agent-';
  const [workflow_id, setWorkflowId] = useState('');
  
  // API mode state
  const [apiMode, setApiMode] = useState(DEFAULT_API_MODE);
  const [currentApiConfig, setCurrentApiConfig] = useState(getApiConfig(DEFAULT_API_MODE));

  // Handle API mode switching
  const handleApiModeChange = (newMode) => {
    if (isChatActive) {
      alert('Please end the current chat session before switching API modes.');
      return;
    }
    setApiMode(newMode);
    setCurrentApiConfig(getApiConfig(newMode));
    setMessages([]);
  };

  useEffect(() => {
    if (chatWindowRef.current) {
      chatWindowRef.current.scrollTop = chatWindowRef.current.scrollHeight;
    }
  }, [messages]);

  const handleStartChat = async () => {
    try {
      let response;
      const newSessionId = Math.random().toString(36).substring(2, 15);
      const newWorkflowId = workflow_id_prefix + newSessionId;
      console.log(`Getting ready to start workflow with id ${newWorkflowId}`);
      response = await fetch(`${currentApiConfig.baseUrl}/start-workflow?workflow_id=${newWorkflowId}`, { method: 'POST' });
      if (response.ok) {
        const result = await response.json();

        // check to see if it has truly been started
        if (result.message === 'Workflow started.') {
          console.log('Workflow has been started.');
          setWorkflowId(newWorkflowId);
          setMessages([{text: defaultHeaderText, type: 'bot'}]);
          setIsChatActive(true);
          setSessionId(newSessionId);
        } else {
          setMessages([{text: `Workflow didn't start. Error ${result.message}`, type: 'bot'}]);
        }
      } else {
        setMessages( [{text: `Bad/invalid response from API: ${response.status}`, type: 'bot'}]);
      }
    } catch (error) {
      console.error('Error starting chat session:', error);
      setMessages([{ text: 'Failed to start chat session.', type: 'bot' }]);
    }
  };

  const handleSend = async () => {
    if (!input.trim() || !sessionId) {
      console.log('either nothing to send or session Id is empty');
      return;
    }

    const userMessage = { text: input, type: 'user' };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    console.log("before sending the prompt, messages are ", messages);

    try {
      const encodedInput = encodeURIComponent(input);
      const response = await fetch(`${currentApiConfig.baseUrl}/send-prompt?workflow_id=${workflow_id}&prompt=${encodedInput}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await response.json();
      
      // Handle immediate response from update handler
      if (data.success && data.chat_interaction && data.chat_interaction.text_response) {
        console.log("Received immediate response:", data.chat_interaction.text_response);
        const botMessage = { text: data.chat_interaction.text_response, type: 'bot' };
        setMessages(prev => [...prev, botMessage]);
      } else if (!data.success) {
        console.error('Error from server:', data.error_message);
        const errorMessage = { 
          text: data.chat_interaction?.text_response || 'Failed to get response from bot.', 
          type: 'bot' 
        };
        setMessages(prev => [...prev, errorMessage]);
      }
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage = { text: 'Failed to get response from bot.', type: 'bot' };
      setMessages(prev => [...prev, errorMessage]);
    }
  };

  const handleEndChat = async () => {
    console.log("Session id is ", sessionId);
    if (!sessionId) {
      return;
    }
    try {
      await fetch(`${currentApiConfig.baseUrl}/end-chat?workflow_id=${workflow_id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId }),
      });
      setMessages(prev => [...prev, { text: 'Chat session ended.', type: 'bot' }]);
      setSessionId(null);
      setIsChatActive(false);
    } catch (error) {
        console.error('Error ending chat session:', error);
    }
  };

  const handleToggleChatState = () => {
    if (isChatActive) {
      handleEndChat();
    } else {
      handleStartChat();
    }
  };

  return (
    <div className="App">
      <div className="header">
        <div className="header-title">Wealth Management Chatbot</div>
        <div className="api-mode-selector">
          <label htmlFor="api-mode">API Mode: </label>
          <select 
            id="api-mode"
            value={apiMode} 
            onChange={(e) => handleApiModeChange(e.target.value)}
            disabled={isChatActive}
          >
            {Object.entries(API_CONFIGS).map(([key, config]) => (
              <option key={key} value={key}>
                {config.name}
              </option>
            ))}
          </select>
          <div className="api-description">
            {currentApiConfig.description}
          </div>
        </div>
      </div>
      <div className="chat-window" ref={chatWindowRef}>
        {messages.map((msg, index) => {
          // Ensure msg.text is a string
          const messageText = typeof msg.text === 'string' ? msg.text : String(msg.text || '');
          
          return (
            <div key={index} className={`message ${msg.type}`}>
              {messageText.split('\n').map((line, i) => (
                    <span key={i}>
                      {line}
                      <br />
                    </span>
              ))}
            </div>
          );
        })}
      </div>
      <div className="input-area">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Type a message..."
          disabled={!isChatActive}
        />
        <button onClick={handleSend} disabled={!isChatActive}>Send</button>
      </div>
      <button
        onClick={handleToggleChatState}
        className={`end-chat-button ${!isChatActive ? 'start-chat-button' : ''}`}
      >
        {isChatActive ? 'End Chat' : 'Start Chat'}
      </button>
    </div>
  );
}

export default App;

