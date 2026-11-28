package ai.jarvis.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import ai.jarvis.mobile.ui.JarvisRoot
import ai.jarvis.mobile.ui.theme.JarvisTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = application as JarvisApp
        setContent {
            JarvisTheme {
                JarvisRoot(app)
            }
        }
    }
}
