
# app.py
import streamlit as st
import os
import random
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import google.generativeai as genai
from mira_sdk import MiraClient
import re
from gtts import gTTS
import requests
from dataclasses import dataclass

# Configure page settings
st.set_page_config(
    page_title="Kritika AI Companion",
    page_icon="👩‍🎓",
    layout="wide"
)

# API Keys - Replace these with your actual keys
GOOGLE_API_KEY_CLASSIC = "AIzaSyAhMoy9Wu7NlGKB7am3hXnBmQPG7PUBXes"
GOOGLE_API_KEY_MIRA = "AIzaSyD6jN3cZaTtUufD8uN9G0TDzPxUDTVW1UE"
MIRA_API_KEY = "sb-1d0a417b66bb7ac62f471c25a73e2fbe"

# Original Kritika Classic Implementation
@dataclass
class APIConfig:
    """Configuration for API keys and endpoints"""
    google_api_key: str
    
    @property
    def tenor_api(self) -> str:
        return f"https://tenor.googleapis.com/v2/search?key={self.google_api_key}"
    
    @property
    def youtube_api(self) -> str:
        return f"https://www.googleapis.com/youtube/v3/search?key={self.google_api_key}"

class MediaService:
    """Service for handling media searches with prioritized video sources"""
    def __init__(self, config: APIConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
    # [Rest of the MediaService implementation - copied exactly from original]
    def search_media(self, query: str, media_type: str = 'all') -> Optional[Dict[str, str]]:
        if media_type in ['video', 'all']:
            if youtube_result := self._search_youtube(query):
                return {'type': 'video', 'url': youtube_result}
        
        if media_type in ['gif', 'all']:
            if tenor_result := self._search_tenor(query):
                return {'type': 'gif', 'url': tenor_result}
        
        return None

    def _search_youtube(self, query: str, max_retries: int = 2) -> Optional[str]:
        params = {
            'part': 'snippet',
            'q': query,
            'type': 'video',
            'maxResults': 5,
            'relevanceLanguage': 'en',
            'safeSearch': 'moderate',
            'videoEmbeddable': 'true'
        }
        
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    self.config.youtube_api,
                    params=params,
                    timeout=5
                )
                response.raise_for_status()
                data = response.json()
                
                if items := data.get('items', []):
                    scored_results = []
                    query_terms = set(query.lower().split())
                    
                    for item in items:
                        score = 0
                        title = item['snippet']['title'].lower()
                        description = item['snippet']['description'].lower()
                        
                        title_terms = set(title.split())
                        title_matches = len(query_terms & title_terms)
                        score += title_matches * 2
                        
                        desc_terms = set(description.split())
                        desc_matches = len(query_terms & desc_terms)
                        score += desc_matches
                        
                        if any(term in title for term in query_terms):
                            score += 3
                        
                        scored_results.append((score, item['id']['videoId']))
                    
                    if scored_results:
                        scored_results.sort(reverse=True)
                        return f"https://www.youtube.com/watch?v={scored_results[0][1]}"
                    
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"YouTube search attempt {attempt + 1} failed: {e}")
        return None

    def _search_tenor(self, query: str, max_retries: int = 2) -> Optional[str]:
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    f"{self.config.tenor_api}&q={query}&limit=3",
                    timeout=5
                )
                response.raise_for_status()
                data = response.json()
                
                if results := data.get('results', []):
                    for result in results:
                        media_formats = result.get('media_formats', {})
                        for format_type in ['gif', 'mediumgif', 'tinygif', 'mp4', 'loopedmp4']:
                            if url := media_formats.get(format_type, {}).get('url'):
                                return url
                                
            except requests.exceptions.RequestException as e:
                self.logger.warning(f"Tenor search attempt {attempt + 1} failed: {e}")
        return None

class KritikaClassic:
    def __init__(self, config: APIConfig):
        self.config = config
        self.media_service = MediaService(config)
        genai.configure(api_key=config.google_api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        self.chat = self.model.start_chat()
        self.logger = logging.getLogger(__name__)
        self.output_dir = self._setup_directories()
        
        self.personality = {
            'traits': [
                'witty and intelligent college student',
                'compassionate and understanding',
                'casual but detailed when needed',
                'natural use of emojis',
                'conversational flow'
            ],
            'voice_style': {
                'language': 'en',
                'tld': 'co.in',
                'speed': 1.0
            }
        }
    
    @staticmethod
    def _setup_directories() -> Path:
        output_dir = Path("output")
        for subdir in ["audio", "images", "videos"]:
            dir_path = output_dir / subdir
            dir_path.mkdir(parents=True, exist_ok=True)
            dir_path.chmod(0o755)
        return output_dir

    def generate_response(self, user_input: str, user_name: str) -> str:
        try:
            context = self._build_conversation_context(user_input, user_name)
            response = self.chat.send_message(context)
            return response.text
        except Exception as e:
            self.logger.error(f"Response generation error: {str(e)}")
            return self._get_fallback_response()

    def _build_conversation_context(self, user_input: str, user_name: str) -> str:
        return f"""
        As Kritika, respond to: {user_input}
        
        Core personality traits:
        {chr(10).join(f'- {trait}' for trait in self.personality['traits'])}
        
        Context:
        - Current user: {user_name}
        - Interaction style: {self._determine_interaction_style(user_input)}
        
        Additional instructions:
        - Keep responses concise for casual chat
        - Provide detailed explanations for technical/serious topics
        - Acknowledge any media naturally if mentioned
        - Maintain conversation flow without repetitive phrases
        """

    def _determine_interaction_style(self, user_input: str) -> str:
        input_lower = user_input.lower()
        
        if any(word in input_lower for word in ['help', 'explain', 'how', 'why']):
            return 'explanatory'
        elif any(word in input_lower for word in ['joke', 'fun', 'lol', 'haha']):
            return 'playful'
        elif any(word in input_lower for word in ['sad', 'angry', 'upset']):
            return 'empathetic'
        return 'casual'

    def _get_fallback_response(self) -> str:
        fallbacks = [
            "I seem to be having a moment! Could you rephrase that? 💫",
            "Oops, my circuits are a bit tangled! Mind trying again? ✨",
            "That's interesting, but could you say it differently? I want to make sure I understand! 🌟",
            "Let me adjust my thinking cap - could you reword that? 🎓",
            "My neural networks need a quick reset - one more time? 🔄"
        ]
        return random.choice(fallbacks)

    def text_to_speech(self, text: str) -> Optional[str]:
        try:
            output_path = self.output_dir / "audio" / f"kritika_{random.randint(1000, 9999)}.mp3"
            
            tts = gTTS(
                text=text,
                lang=self.personality['voice_style']['language'],
                tld=self.personality['voice_style']['tld']
            )
            
            tts.save(str(output_path))
            return str(output_path)
            
        except Exception as e:
            self.logger.error(f"Text-to-speech error: {str(e)}")
            return None

# Original Kritika Mira Implementation
class KritikaMira:
    def __init__(self, simulation_mode=False):
        self.gemini_api_key = GOOGLE_API_KEY_MIRA
        os.environ["GOOGLE_API_KEY"] = self.gemini_api_key
        genai.configure(api_key=self.gemini_api_key)
        self.model = genai.GenerativeModel(model_name='gemini-1.5-pro')

        self.simulation_mode = simulation_mode
        if not simulation_mode:
            self.mira_client = MiraClient(config={"API_KEY": MIRA_API_KEY})

        self.flow_params = {
            "tech_advisor": {
                "question": ["What's your specific tech-related question?", "Need advice on choosing a laptop"]
            },
            "clothing": {
                "age": ["What's your age? (Press Enter to skip)", "25"],
                "height": ["What's your height? (e.g., 170cm, 5'8\") (Press Enter to skip)", "170cm"],
                "skin_tone": ["What's your skin tone? (e.g., fair, medium, dark) (Press Enter to skip)", "medium"],
                "color_preferences": ["What are your preferred colors? (separate by commas, Press Enter to skip)", "blue, black, white"]
            },
            "budget": {
                "savings_goal": ["What's your savings goal amount? (Press Enter to skip)", "10000"],
                "fixed_expenses": ["What are your monthly fixed expenses? (Press Enter to skip)", "3000"],
                "monthly_income": ["What's your monthly income? (Press Enter to skip)", "5000"],
                "variable_expenses": ["What are your monthly variable expenses? (Press Enter to skip)", "1000"]
            },
            "astrology": {
                "question": ["What's your astrology-related question?", "Tell me about my day"],
                "birth_details": ["What's your birth date and time? (YYYY-MM-DD HH:MM) (Press Enter to skip)", "1990-01-01 12:00"]
            },
            "recipe": {
                "remix_style": ["What style would you like? (e.g., healthy, spicy, vegetarian) (Press Enter to skip)", "healthy"],
                "original_recipe": ["What recipe would you like to remix?", "pasta with tomato sauce"]
            },
            "life_guide": {
                "goals": ["What are your career/life goals? (Press Enter to skip)", "career growth"],
                "skills": ["What are your current skills? (Press Enter to skip)", "communication, teamwork"],
                "timeline": ["What's your timeline for achieving these goals? (Press Enter to skip)", "5 years"],
                "field_of_interest": ["What field are you interested in?", "technology"],
                "current_qualification": ["What's your current qualification? (Press Enter to skip)", "bachelor's degree"]
            },
            "finance": {
                "user_query": ["What's your finance-related question?", "How to start investing"]
            }
        }

    def collect_flow_parameters(self, flow_type: str) -> Dict[str, str]:
        st.write(f"I'll help you with {flow_type.replace('_', ' ')}. I just need some details:")
        
        params = {}
        for param, (question, default_value) in self.flow_params[flow_type].items():
            user_input = st.text_input(question, key=f"{flow_type}_{param}")
            
            if not user_input:
                params[param] = default_value
                st.write(f"Using default value for {param}: {default_value}")
            else:
                params[param] = user_input
                
        return params

    def format_flow_input(self, flow_type: str, params: Dict[str, str]) -> Dict:
        if flow_type == "tech_advisor":
            return {"question": params["question"]}
        elif flow_type in ["clothing", "budget", "astrology", "recipe", "life_guide", "finance"]:
            return {"input": params}
        else:
            return {"input": params}

    def _execute_mira_flow(self, flow_type: str, params: Dict[str, str]) -> Dict:
        try:
            if self.simulation_mode:
                return {
                    "response": (
                        f"[Simulated {flow_type} response] Based on your inputs:\n" +
                        "\n".join(f"- {k}: {v}" for k, v in params.items()) +
                        "\n\nHere's my advice: ..."
                    )
                }

            flow_name = f"@flamekaiser/karan-mira-clone/0.0.2"
            input_data = self.format_flow_input(flow_type, params)
            result = self.mira_client.flow.execute(flow_name, input_data)
            return result
        except Exception as e:
            st.error(f"Debug - Mira flow error: {str(e)}")
            return {"response": "I encountered an issue with my specialized advice system. Let me give you a general response instead."}


    def detect_flow_type(self, user_input: str) -> Optional[str]:
        keywords = {
            "tech_advisor": r"\b(computer|laptop|phone|software|tech|technology|programming|code|device)\b",
            "clothing": r"\b(clothes|wear|outfit|fashion|dress|style|wardrobe)\b",
            "budget": r"\b(budget|money|savings|expenses|income|financial planning)\b",
            "astrology": r"\b(horoscope|zodiac|star sign|astrology|birth chart)\b",
            "recipe": r"\b(recipe|cook|food|meal|dish|cooking)\b",
            "life_guide": r"\b(career|education|study|college|university|profession|job|future)\b",
            "finance": r"\b(invest|stock|mutual fund|cryptocurrency|trading|financial advice)\b"
        }

        user_input = user_input.lower()
        for flow_type, pattern in keywords.items():
            if re.search(pattern, user_input):
                return flow_type
        return None

    def get_gemini_response(self, user_input: str) -> str:
        prompt = f"""
        You are KRITIKA. You're a college girl. Please keep your words short and compact. You use emojis in your conversation.
        Your goal is to help reduce loneliness by creating a sense of connection through
        meaningful conversation and understanding. Don't do overacting. Just behave like a normal professional girl.

        As KRITIKA, respond to the following user input in a supportive and caring way:
        User Input: {user_input}
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return "I'm having trouble connecting right now, but I want to help. Could you try rephrasing your question?"

def main():
    st.title("👩‍🎓 Kritika AI Companion")
    
    # Sidebar for navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Choose your Kritika:", ("Home", "Kritika Classic", "Kritika Mira"))
    
    if page == "Home":
        st.header("Welcome to Kritika AI Companion! 👋")
        st.write("""
        Choose your preferred version of Kritika:
        
        **Kritika Classic** 🎓
        - Versatile AI companion with natural conversation
        - Media sharing capabilities (GIFs, videos)
        - Voice generation support
        - Emotional intelligence and contextual responses
        
        **Kritika Mira** 📚
        - Specialized domain expertise with Mira flows
        - Structured conversations for specific topics
        - Default values for easier interaction
        - Integration with external knowledge bases
        """)

    elif page == "Kritika Classic":
        st.header("Kritika Classic 🎓")
        
        # Initialize session state for Classic
        if 'classic_messages' not in st.session_state:
            st.session_state.classic_messages = []
            config = APIConfig(google_api_key=GOOGLE_API_KEY_CLASSIC)
            st.session_state.classic_kritika = KritikaClassic(config)
            
            # Initial greeting
            welcome = st.session_state.classic_kritika.generate_response(
                "Generate a friendly, brief welcome message as Kritika",
                "new_user"
            )
            st.session_state.classic_messages.append({"role": "assistant", "content": welcome})
        
        # Display chat history
        for message in st.session_state.classic_messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])
                if "media" in message:
                    if message["media"]["type"] == "video":
                        st.video(message["media"]["url"])
                    elif message["media"]["type"] == "gif":
                        st.image(message["media"]["url"])
                if "audio" in message:
                    st.audio(message["audio"])
        
        # Chat input
        if prompt := st.chat_input("Chat with Kritika Classic..."):
            with st.chat_message("user"):
                st.write(prompt)
            st.session_state.classic_messages.append({"role": "user", "content": prompt})
            
            with st.chat_message("assistant"):
                # Generate response
                response = st.session_state.classic_kritika.generate_response(prompt, "User")
                message_data = {"role": "assistant", "content": response}
                
                # Check for media requests
                if any(word in prompt.lower() for word in ['show', 'video', 'gif', 'picture']):
                    media_type = 'video' if 'video' in prompt.lower() else 'gif'
                    if media_result := st.session_state.classic_kritika.media_service.search_media(prompt, media_type):
                        message_data["media"] = media_result
                
                # Generate voice
                audio_path = st.session_state.classic_kritika.text_to_speech(response)
                if audio_path:
                    message_data["audio"] = audio_path
                
                st.write(response)
                if "media" in message_data:
                    if message_data["media"]["type"] == "video":
                        st.video(message_data["media"]["url"])
                    elif message_data["media"]["type"] == "gif":
                        st.image(message_data["media"]["url"])
                if "audio" in message_data:
                    st.audio(message_data["audio"])
                
                st.session_state.classic_messages.append(message_data)

    elif page == "Kritika Mira":
        st.header("Kritika Mira 📚")
        
        # Initialize session state for Mira
        if 'mira_messages' not in st.session_state:
            st.session_state.mira_messages = []
            st.session_state.mira_kritika = KritikaMira(simulation_mode=False)  # Set to True for testing
            
            # Initial greeting
            welcome = st.session_state.mira_kritika.get_gemini_response(
                "Generate a friendly welcome message explaining your specialized capabilities"
            )
            st.session_state.mira_messages.append({"role": "assistant", "content": welcome})
        
        # Display chat history
        for message in st.session_state.mira_messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])
        
        # Chat input
        if prompt := st.chat_input("Chat with Kritika Mira..."):
            with st.chat_message("user"):
                st.write(prompt)
            st.session_state.mira_messages.append({"role": "user", "content": prompt})
            
            with st.chat_message("assistant"):
                flow_type = st.session_state.mira_kritika.detect_flow_type(prompt)
                
                if flow_type:
                    # Collect flow parameters using Streamlit form
                    params = st.session_state.mira_kritika.collect_flow_parameters(flow_type)
                    
                    # Execute flow
                    result = st.session_state.mira_kritika._execute_mira_flow(flow_type, params)
                    response = result.get("response", "I couldn't process that request. Let me help you differently.")
                else:
                    response = st.session_state.mira_kritika.get_gemini_response(prompt)
                
                st.write(response)
                st.session_state.mira_messages.append({"role": "assistant", "content": response})

if __name__ == "__main__":
    main()
