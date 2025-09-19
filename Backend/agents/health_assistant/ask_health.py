from flask import Blueprint, request, jsonify
from agents.health_assistant.analyzer import analyze_health_query

health_bp = Blueprint("health_bp", __name__)

@health_bp.route("/health/ask", methods=["POST"])
def health_ask():
    try:
        data = request.get_json()
        query = data.get("query", "").strip()
        health_data = data.get("health_data", {})

        if not query:
            return jsonify({"error": "Missing query field"}), 400

        if not isinstance(health_data, dict) or not health_data:
            return jsonify({"error": "Invalid or missing health_data"}), 400

        print(f"🎙️ Query: {query}")
        print(f"📊 Health Data: {health_data}")

        # Analyze using GPT
        response = analyze_health_query(query, health_data)
        return jsonify({"response": response})

    except Exception as e:
        print(f"❌ Error in /health/ask: {e}")
        return jsonify({"error": "Server error"}), 500
