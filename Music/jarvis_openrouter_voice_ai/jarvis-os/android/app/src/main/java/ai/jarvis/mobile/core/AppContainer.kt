package ai.jarvis.mobile.core

import android.content.Context
import ai.jarvis.mobile.core.agent.AgentOrchestrator
import ai.jarvis.mobile.core.data.JarvisDatabase
import ai.jarvis.mobile.core.data.SettingsStore
import ai.jarvis.mobile.core.network.JarvisApi
import ai.jarvis.mobile.core.system.DeviceController
import ai.jarvis.mobile.core.system.ToolRegistry
import ai.jarvis.mobile.core.voice.SpeechController
import ai.jarvis.mobile.core.voice.VoiceRecognizer

class AppContainer(context: Context) {
    val settingsStore = SettingsStore(context)
    val database = JarvisDatabase.create(context)
    val api = JarvisApi(settingsStore)
    val device = DeviceController(context)
    val tools = ToolRegistry(device)
    val agent = AgentOrchestrator(api, tools, settingsStore, database)
    val speech = SpeechController(context, api, settingsStore)
    val voice = VoiceRecognizer(context)
}
