package ai.jarvis.mobile.ui.vision

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraControl
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.ZoomIn
import androidx.compose.material.icons.filled.ZoomOut
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ai.jarvis.mobile.ui.components.CyanDivider
import ai.jarvis.mobile.ui.components.HudNotices
import ai.jarvis.mobile.ui.components.HudPanel
import ai.jarvis.mobile.ui.components.Pill
import ai.jarvis.mobile.ui.components.SectionLabel
import ai.jarvis.mobile.ui.theme.Amber
import ai.jarvis.mobile.ui.theme.Cyan
import ai.jarvis.mobile.ui.theme.CyanBright
import ai.jarvis.mobile.ui.theme.CyanDim
import ai.jarvis.mobile.ui.theme.Danger
import ai.jarvis.mobile.ui.theme.Panel
import ai.jarvis.mobile.ui.theme.Success
import ai.jarvis.mobile.ui.theme.TextMuted
import ai.jarvis.mobile.ui.theme.TextPrimary
import ai.jarvis.mobile.ui.theme.TextSecondary
import java.io.File
import kotlinx.coroutines.delay

@Composable
fun VisionScreen(
    viewModel: VisionViewModel,
    bottomPadding: PaddingValues,
) {
    val ui by viewModel.ui.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var hasCamera by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }
    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }
    var cameraProvider by remember { mutableStateOf<ProcessCameraProvider?>(null) }
    var cameraControl by remember { mutableStateOf<CameraControl?>(null) }
    var cameraError by remember { mutableStateOf<String?>(null) }
    var zoomRatio by remember { mutableStateOf(1f) }
    var zoomMax by remember { mutableStateOf(8f) }

    val cameraPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasCamera = granted
        if (!granted) {
            HudNotices.show("Camera permission is required for live vision.")
        }
    }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri != null) {
            runCatching {
                val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                    ?: error("Could not read that image")
                if (bytes.size > 12 * 1024 * 1024) error("Image is larger than 12 MB")
                val mime = context.contentResolver.getType(uri) ?: "image/jpeg"
                viewModel.analyze(bytes, mime)
            }.onFailure {
                HudNotices.show(it.message ?: "Image could not be read")
            }
        }
    }

    DisposableEffect(hasCamera) {
        onDispose {
            runCatching { cameraProvider?.unbindAll() }
            imageCapture = null
        }
    }

    val capturePhoto: () -> Unit = {
        val capture = imageCapture
        if (capture == null) {
            HudNotices.show("Camera is not ready yet.")
        } else {
            val file = File(context.cacheDir, "vision_${System.currentTimeMillis()}.jpg")
            val options = ImageCapture.OutputFileOptions.Builder(file).build()
            capture.takePicture(
                options,
                ContextCompat.getMainExecutor(context),
                object : ImageCapture.OnImageSavedCallback {
                    override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                        runCatching { file.readBytes() }
                            .onSuccess { bytes ->
                                viewModel.analyze(bytes, "image/jpeg")
                                runCatching { file.delete() }
                            }
                            .onFailure {
                                HudNotices.show("Capture could not be read.")
                            }
                    }

                    override fun onError(exception: ImageCaptureException) {
                        HudNotices.show("Capture failed: ${exception.message}")
                    }
                },
            )
        }
    }

    fun zoomIn() {
        val control = cameraControl
        if (control == null) {
            HudNotices.show("Camera zoom is not ready yet.")
            return
        }
        val next = (zoomRatio * 1.25f).coerceIn(1f, zoomMax)
        zoomRatio = next
        control.setZoomRatio(next)
    }

    fun zoomOut() {
        val control = cameraControl
        if (control == null) {
            HudNotices.show("Camera zoom is not ready yet.")
            return
        }
        val next = (zoomRatio / 1.25f).coerceIn(1f, zoomMax)
        zoomRatio = next
        control.setZoomRatio(next)
    }

    val scrollState = rememberScrollState()
    LaunchedEffect(ui.result) {
        if (ui.result != null) {
            delay(180)
            scrollState.animateScrollTo(scrollState.maxValue)
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            .padding(horizontal = 16.dp),
    ) {
        Spacer(Modifier.height(10.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("OPTICAL SENSOR", style = MaterialTheme.typography.labelLarge, color = CyanBright)
                Text(
                    "Camera and gallery analysis through the vision model",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
            }
            if (ui.result != null) {
                IconButton(onClick = viewModel::clear) {
                    Icon(Icons.Filled.Close, contentDescription = "Clear result", tint = TextSecondary)
                }
            }
        }

        Spacer(Modifier.height(10.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .height(286.dp)
                .clip(RoundedCornerShape(18.dp))
                .background(Color(0xFF02090F))
                .border(1.dp, Cyan.copy(alpha = 0.30f), RoundedCornerShape(18.dp)),
        ) {
            if (hasCamera) {
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = { viewContext ->
                        val previewView = PreviewView(viewContext).apply {
                            scaleType = PreviewView.ScaleType.FILL_CENTER
                        }
                        val future = ProcessCameraProvider.getInstance(viewContext)
                        future.addListener({
                            runCatching {
                                val provider = future.get()
                                cameraProvider = provider
                                val preview = Preview.Builder().build().also {
                                    it.setSurfaceProvider(previewView.surfaceProvider)
                                }
                                val capture = ImageCapture.Builder()
                                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                                    .build()
                                imageCapture = capture
                                provider.unbindAll()
                                val camera = provider.bindToLifecycle(
                                    lifecycleOwner,
                                    CameraSelector.DEFAULT_BACK_CAMERA,
                                    preview,
                                    capture,
                                )
                                cameraControl = camera.cameraControl
                            }.onFailure {
                                cameraError = "Camera could not start: ${it.message}"
                            }
                        }, ContextCompat.getMainExecutor(viewContext))
                        previewView
                    },
                )
                CameraOverlay()
            } else {
                Column(
                    Modifier.fillMaxSize().padding(22.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Icon(
                        Icons.Filled.CameraAlt,
                        contentDescription = null,
                        tint = CyanDim,
                        modifier = Modifier.size(36.dp),
                    )
                    Spacer(Modifier.height(10.dp))
                    Text("Camera access is off", style = MaterialTheme.typography.titleMedium, color = TextPrimary)
                    Text(
                        "Grant camera permission to scan the world, or choose an existing image below.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextSecondary,
                    )
                    Spacer(Modifier.height(12.dp))
                    TextButton(onClick = { cameraPermission.launch(Manifest.permission.CAMERA) }) {
                        Text("Enable camera", color = Cyan)
                    }
                }
            }

            if (hasCamera) {
                Column(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(12.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        IconButton(onClick = { zoomOut() }, enabled = hasCamera) {
                            Icon(
                                Icons.Filled.ZoomOut,
                                contentDescription = "Zoom out",
                                tint = Cyan,
                                modifier = Modifier.size(30.dp),
                            )
                        }
                        Text(
                            "ZOOM",
                            style = MaterialTheme.typography.labelSmall,
                            color = Cyan,
                            modifier = Modifier.padding(horizontal = 6.dp),
                        )
                        IconButton(onClick = { zoomIn() }, enabled = hasCamera) {
                            Icon(
                                Icons.Filled.ZoomIn,
                                contentDescription = "Zoom in",
                                tint = Cyan,
                                modifier = Modifier.size(30.dp),
                            )
                        }
                    }
                }
            }

            if (ui.analyzing) {
                Box(
                    Modifier
                        .fillMaxSize()
                        .background(Color(0xCC02090F)),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        CircularProgressIndicator(color = Cyan, strokeWidth = 2.dp)
                        Spacer(Modifier.height(10.dp))
                        Text(
                            "ANALYZING FRAME",
                            style = MaterialTheme.typography.labelSmall,
                            color = Cyan,
                        )
                    }
                }
            }

            cameraError?.let { message ->
                Text(
                    message,
                    style = MaterialTheme.typography.labelSmall,
                    color = Danger,
                    modifier = Modifier
                        .align(Alignment.BottomStart)
                        .padding(12.dp)
                        .background(Color(0xCC02090F), RoundedCornerShape(8.dp))
                        .padding(8.dp),
                )
            }
        }

        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .size(58.dp)
                    .clip(CircleShape)
                    .background(Cyan.copy(alpha = 0.12f))
                    .border(1.5.dp, Cyan, CircleShape)
                    .clickable(enabled = hasCamera, onClick = capturePhoto),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Filled.CameraAlt,
                    contentDescription = "Capture",
                    tint = if (hasCamera) Cyan else TextMuted,
                    modifier = Modifier.size(25.dp),
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text("CAPTURE", style = MaterialTheme.typography.labelSmall, color = Cyan)
                Text(
                    "Tap the shutter to analyze what the camera sees.",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
            }
            Pill(if (ui.analyzing) "BUSY" else "READY", if (ui.analyzing) Amber else Success)
            Spacer(Modifier.width(8.dp))
            IconButton(
                onClick = { gallery.launch("image/*") },
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .background(Panel)
                    .border(1.dp, CyanDim.copy(alpha = 0.4f), CircleShape),
            ) {
                Icon(Icons.Filled.PhotoLibrary, contentDescription = "Choose image", tint = Cyan)
            }
        }

        Spacer(Modifier.height(14.dp))
        SectionLabel("Analysis mode")
        Spacer(Modifier.height(7.dp))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(7.dp),
            verticalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            ModeChip("Identify", "identify", ui.mode, viewModel::setMode)
            ModeChip("Read text", "text", ui.mode, viewModel::setMode)
            ModeChip("Translate", "translate", ui.mode, viewModel::setMode)
            ModeChip("Solve", "solve", ui.mode, viewModel::setMode)
            ModeChip("Describe", "describe", ui.mode, viewModel::setMode)
        }

        Spacer(Modifier.height(10.dp))
        OutlinedTextField(
            value = ui.question,
            onValueChange = viewModel::setQuestion,
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("Optional question about the image", color = TextMuted, fontSize = 14.sp) },
            maxLines = 2,
            shape = RoundedCornerShape(14.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Cyan.copy(alpha = 0.6f),
                unfocusedBorderColor = CyanDim.copy(alpha = 0.35f),
                focusedContainerColor = Panel.copy(alpha = 0.65f),
                unfocusedContainerColor = Panel.copy(alpha = 0.45f),
                cursorColor = Cyan,
                focusedTextColor = TextPrimary,
                unfocusedTextColor = TextPrimary,
            ),
        )

        if (ui.error != null) {
            Spacer(Modifier.height(12.dp))
            HudPanel(accent = Danger, modifier = Modifier.fillMaxWidth()) {
                Text("VISION LINK FAILED", style = MaterialTheme.typography.labelSmall, color = Danger)
                Spacer(Modifier.height(5.dp))
                Text(ui.error ?: "", style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
                TextButton(onClick = viewModel::retry) { Text("Retry", color = Cyan) }
            }
        }

        ui.result?.let { result ->
            Spacer(Modifier.height(12.dp))
            HudPanel(title = "Vision result", modifier = Modifier.fillMaxWidth()) {
                if (ui.provider.isNotBlank()) {
                    Pill(
                        "${ui.provider} • ${ui.model}",
                        Cyan,
                        modifier = Modifier.padding(bottom = 8.dp),
                        maxLines = 2,
                    )
                }
                if (result.description.isNotBlank()) {
                    Text(result.description, style = MaterialTheme.typography.bodyLarge, color = TextPrimary)
                } else {
                    Text("The model returned no description.", style = MaterialTheme.typography.bodyMedium, color = TextMuted)
                }
                if (result.answer.isNotBlank()) {
                    Spacer(Modifier.height(10.dp))
                    SectionLabel("Answer")
                    Text(result.answer, style = MaterialTheme.typography.bodyLarge, color = CyanBright)
                }
                if (result.text.isNotBlank()) {
                    Spacer(Modifier.height(10.dp))
                    SectionLabel("Extracted text")
                    Text(
                        result.text,
                        style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                        color = TextPrimary,
                        maxLines = 12,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                if (result.translation.isNotBlank()) {
                    Spacer(Modifier.height(10.dp))
                    SectionLabel("Translation")
                    Text(result.translation, style = MaterialTheme.typography.bodyMedium, color = TextPrimary)
                }
                if (result.objects.isNotEmpty()) {
                    Spacer(Modifier.height(10.dp))
                    SectionLabel("Objects")
                    result.objects.take(12).forEach { obj ->
                        Text(
                            "• ${obj.label}${if (obj.details.isNotBlank()) " — ${obj.details}" else ""}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = TextSecondary,
                        )
                    }
                }
                if (result.safety.isNotBlank() && !result.safety.equals("ok", ignoreCase = true)) {
                    Spacer(Modifier.height(10.dp))
                    CyanDivider()
                    Spacer(Modifier.height(8.dp))
                    Text(result.safety, style = MaterialTheme.typography.labelSmall, color = Amber)
                }
            }
        }

        Spacer(Modifier.height(bottomPadding.calculateBottomPadding() + 24.dp))
    }
}

@Composable
private fun CameraOverlay() {
    Canvas(Modifier.fillMaxSize().padding(14.dp)) {
        val length = 26.dp.toPx()
        val stroke = 1.8.dp.toPx()
        val color = Cyan.copy(alpha = 0.8f)
        drawLine(color, Offset(0f, 0f), Offset(length, 0f), stroke, StrokeCap.Round)
        drawLine(color, Offset(0f, 0f), Offset(0f, length), stroke, StrokeCap.Round)
        drawLine(color, Offset(size.width, 0f), Offset(size.width - length, 0f), stroke, StrokeCap.Round)
        drawLine(color, Offset(size.width, 0f), Offset(size.width, length), stroke, StrokeCap.Round)
        drawLine(color, Offset(0f, size.height), Offset(length, size.height), stroke, StrokeCap.Round)
        drawLine(color, Offset(0f, size.height), Offset(0f, size.height - length), stroke, StrokeCap.Round)
        drawLine(color, Offset(size.width, size.height), Offset(size.width - length, size.height), stroke, StrokeCap.Round)
        drawLine(color, Offset(size.width, size.height), Offset(size.width, size.height - length), stroke, StrokeCap.Round)
        val center = Offset(size.width / 2f, size.height / 2f)
        drawLine(Cyan.copy(alpha = 0.45f), Offset(center.x - 12.dp.toPx(), center.y), Offset(center.x + 12.dp.toPx(), center.y), 1f)
        drawLine(Cyan.copy(alpha = 0.45f), Offset(center.x, center.y - 12.dp.toPx()), Offset(center.x, center.y + 12.dp.toPx()), 1f)
    }
}

@Composable
private fun ModeChip(label: String, value: String, selected: String, onSelect: (String) -> Unit) {
    Box(
        Modifier
            .clip(RoundedCornerShape(9.dp))
            .background(if (selected == value) Cyan.copy(alpha = 0.14f) else Panel.copy(alpha = 0.5f))
            .border(
                1.dp,
                if (selected == value) Cyan.copy(alpha = 0.55f) else CyanDim.copy(alpha = 0.25f),
                RoundedCornerShape(9.dp),
            )
            .clickable { onSelect(value) }
            .padding(horizontal = 12.dp, vertical = 7.dp),
    ) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = if (selected == value) Cyan else TextMuted,
        )
    }
}
