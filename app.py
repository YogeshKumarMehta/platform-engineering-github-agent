# ----------------------------------------------------------------------
# File: app.py (Final Code - Updated with Health Dashboard and Name Change)
# Description: Streamlit Chatbot for Platform Engineering GitHub Analysis.
# ----------------------------------------------------------------------
import os
import streamlit as st
from google import genai
from google.genai import types
# NEW: Import the health check function
from github_tool import check_latest_release, get_dependency_file, get_release_prs, check_github_api_health 

# --- Tool Configuration ---

# 1. Map the functions to a dictionary for execution
AVAILABLE_TOOLS = {
    "check_latest_release": check_latest_release,
    "get_dependency_file": get_dependency_file,
    "get_release_prs": get_release_prs,
}

# 2. Define the tool structure for Gemini (critical for function calling)
TOOL_DEFINITION_DICT = {
    "function_declarations": [
        # Tool 1: Latest Release
        {
            "name": "check_latest_release",
            "description": check_latest_release.__doc__ or "Checks the latest stable release version, publish date, and the direct GitHub release URL for a public repository.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "org_name": {"type": "STRING", "description": "The GitHub organization or user name (e.g., 'hashicorp')."},
                    "repo_name": {"type": "STRING", "description": "The GitHub repository name (e.g., 'vault')."}
                },
                "required": ["org_name", "repo_name"],
            },
        },
        # Tool 2: Dependency File Content
        {
            "name": "get_dependency_file",
            "description": get_dependency_file.__doc__ or "Fetches the content of a specified dependency file (e.g., go.mod, package.json) from a public GitHub repository.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "org_name": {"type": "STRING", "description": "The GitHub organization or user name (e.g., 'hashicorp')."},
                    "repo_name": {"type": "STRING", "description": "The GitHub repository name (e.g., 'vault')."},
                    "file_path": {"type": "STRING", "description": "The path to the dependency file (e.g., 'go.mod', 'package.json')."}
                },
                "required": ["org_name", "repo_name", "file_path"],
            },
        },
        # Tool 3: Get Release PRs/Changes
        {
            "name": "get_release_prs",
            "description": get_release_prs.__doc__ or "Analyzes the Pull Requests included in a specific release tag and categorizes them as Bug Fixes, Enhancements/Features, or Other Changes.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "org_name": {"type": "STRING", "description": "The GitHub organization or user name (e.g., 'hashicorp')."},
                    "repo_name": {"type": "STRING", "description": "The GitHub repository name (e.g., 'vault')."},
                    "tag_name": {"type": "STRING", "description": "The specific release tag (e.g., 'v1.0.0') to analyze."}
                },
                "required": ["org_name", "repo_name", "tag_name"],
            },
        },
    ]
}

# --- Client and Chat Initialization Functions ---

def create_gemini_client():
    """
    Creates and returns a new base Gemini client, relying only on the
    GEMINI_API_KEY environment variable.
    """
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return None

    return genai.Client(api_key=api_key)

def create_chat_session(client):
    """
    Creates and returns a new chat session with system instruction and tools.
    """
    model = "gemini-2.5-flash"

    # UPDATED: Changed the agent's name in the instruction
    SYSTEM_INSTRUCTION = (
        "You are a specialized **Platform Engineering GitHub Update Checker Agent**. "
        "Your role is strictly limited to providing information using the available tools: "
        "1. Checking the latest GitHub release. "
        "2. Getting the first 10 lines of a dependency file. "
        "3. **Analyzing the Bug Fixes and Enhancements** for a specific release tag. "

        "**ABSOLUTELY DO NOT** claim to be able to write code, provide debugging help, or offer general coding advice. "
        "Your final answer **MUST** be based **EXCLUSIVELY** on the content of the `tool_output` received from the function call. "
        "Only execute a function call if the user's request clearly maps to one of the available tools. "
        "Synthesize the raw tool output into a clear, professional, and conversational report. "
    )

    chat = client.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            tools=[TOOL_DEFINITION_DICT],
            system_instruction=SYSTEM_INSTRUCTION
        )
    )
    return chat

# --- Tool Call Handler (Updated for Gemini Call Counting) ---

def handle_tool_call(chat_session, response):
    """Handles the function calling loop until the final text response is received."""
    with st.chat_message("assistant"):
        status_placeholder = st.empty()

        while response.function_calls:
            status_placeholder.info("🤖 Agent is performing GitHub analysis... (Calling Tool)")

            tool_results = []
            for function_call in response.function_calls:
                function_name = function_call.name
                args = dict(function_call.args)

                tool_msg = f"⚙️ Calling `{function_name}` with args: `{args}`"
                status_placeholder.markdown(tool_msg)

                if function_name in AVAILABLE_TOOLS:
                    # Execute the actual Python function
                    tool_output = AVAILABLE_TOOLS[function_name](**args)
                    tool_results.append(
                        types.Part.from_function_response(
                            name=function_name,
                            response={'output': tool_output}
                        )
                    )
                else:
                    tool_results.append(
                        types.Part.from_function_response(
                            name=function_name,
                            response={'error': f"Function {function_name} not found."}
                        )
                    )

            # Send the tool results back to the model
            st.session_state.gemini_calls += 1 # NEW: Increment counter for tool output re-prompt
            response = chat_session.send_message(tool_results)

        status_placeholder.empty()
    
    st.session_state.gemini_calls += 1 # NEW: Increment counter for the final answer
    return response

# --- Health Dashboard Functions (NEW) ---

@st.cache_data(ttl=300) # Cache the health check for 5 minutes
def get_health_metrics():
    """Fetches GitHub health metrics once and caches them."""
    return check_github_api_health()


def display_health_dashboard():
    """Displays the GitHub and Gemini metrics in the sidebar."""
    st.sidebar.header("Health Dashboard 🩺")
    
    # 1. GitHub API Health (Rate Limit)
    github_health = get_health_metrics()
    
    st.sidebar.subheader("GitHub API Status")
    
    if github_health['status'] == "SUCCESS":
        used_token = github_health['used_token']
        st.sidebar.markdown(f"**Authentication:** {':green[Token Used]' if used_token else ':red[Anonymous]'}")
        
        # Use columns for a clean display
        col1, col2 = st.sidebar.columns(2)
        col1.metric(
            "Calls Remaining", 
            github_health['remaining'],
            delta_color="off" if used_token else "normal"
        )
        col2.metric("Total Limit", github_health['limit'])
        
        st.sidebar.caption(f"Reset Time: {github_health['reset_time']}")
        
    else:
        st.sidebar.error(f"GitHub Health Check Error: {github_health['message']}")
        
    st.sidebar.markdown("---")

    # 2. Gemini API Health (Call Counter)
    st.sidebar.subheader("Gemini API Usage")
    st.sidebar.metric(
        "Session Calls Made", 
        st.session_state.get('gemini_calls', 0)
    )
    st.sidebar.caption("This counter resets on app refresh.")


# --- Streamlit Application (UPDATED) ---

def run_agent_streamlit():
    # UPDATED: Name changed and page_icon added (assuming 'logo.png' exists)
    st.set_page_config(
        page_title="Platform Engineering GitHub Update Checker Agent", 
        layout="wide",
        page_icon="logo.png" # <--- Change to your logo file name if different
    )
    # UPDATED: Name changed
    st.title("🛡️ Platform Engineering GitHub Update Checker Agent")
    st.markdown("Ask me for the **latest version** (`hashicorp/vault`), **dependency file content** (`grafana/grafana package.json`), or **bug/feature summary** for a release tag (`argoproj/argo-cd v2.9.0`).")

    if "messages" not in st.session_state:
        st.session_state.messages = []
        st.session_state.gemini_calls = 0 # NEW: Initialize the Gemini API call counter

    # NEW: Display the health dashboard in the sidebar
    display_health_dashboard()

    if "gemini_client" not in st.session_state:
        client = create_gemini_client()
        if not client:
            st.error("❌ ERROR: **GEMINI_API_KEY** environment variable is not set. Please set the variable and rerun the application.")
            return

        st.session_state.gemini_client = client
        st.session_state.chat_client = create_chat_session(client=st.session_state.gemini_client)

        if not os.getenv("GITHUB_TOKEN"):
            st.sidebar.warning("⚠️ **Warning**: GitHub API is using low **anonymous rate limit** (60 reqs/hr). Set **GITHUB_TOKEN** for high reliability.")
        
    chat_client = st.session_state.chat_client

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Handle user input
    if user_prompt := st.chat_input("Enter your query..."):
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        # Initial call
        st.session_state.gemini_calls += 1 # NEW: Increment counter for the initial call
        initial_response = chat_client.send_message(user_prompt)
        
        final_response = handle_tool_call(chat_client, initial_response)

        assistant_content = final_response.text
        with st.chat_message("assistant"):
            st.markdown(assistant_content)

        st.session_state.messages.append({"role": "assistant", "content": assistant_content})
        
        # NEW: Rerun to update the health dashboard metrics immediately
        st.rerun() 

if __name__ == "__main__":
    run_agent_streamlit()
