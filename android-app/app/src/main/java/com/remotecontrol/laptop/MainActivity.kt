package com.remotecontrol.laptop

import android.annotation.SuppressLint
import android.content.Context
import android.os.Bundle
import android.view.View
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions

/**
 * Laptop Touch Control - Android client.
 *
 * Pair by scanning the QR code printed by server.py, or type the address
 * manually. The remote-control UI itself is the server's web page in a
 * full-screen WebView (MJPEG stream + WebSocket input channel).
 */
class MainActivity : AppCompatActivity() {

    private lateinit var connectPanel: LinearLayout
    private lateinit var serverInput: EditText
    private lateinit var connectBtn: Button
    private lateinit var scanBtn: Button
    private lateinit var webView: WebView

    // disconnect happens via double back-press - nothing overlays the screen
    private var lastBackPress = 0L

    // QR scanner: result is the encoded URL, e.g. http://192.168.1.10:8080
    private val qrScanner = registerForActivityResult(ScanContract()) { result ->
        if (result.contents != null) {
            val url = result.contents
                .removePrefix("http://")
                .removePrefix("https://")
                .trimEnd('/')
            serverInput.setText(url)
            connect()
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        connectPanel = findViewById(R.id.connectPanel)
        serverInput = findViewById(R.id.serverInput)
        connectBtn = findViewById(R.id.connectBtn)
        scanBtn = findViewById(R.id.scanBtn)
        webView = findViewById(R.id.webView)

        // remember last server address
        val prefs = getSharedPreferences("rtc", Context.MODE_PRIVATE)
        serverInput.setText(prefs.getString("server", ""))

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true           // page stores the PIN in localStorage
            mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_NO_CACHE
            useWideViewPort = true
            loadWithOverviewMode = true
            builtInZoomControls = false
            displayZoomControls = false
        }
        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                Toast.makeText(this@MainActivity,
                    "Connected - press back twice to disconnect",
                    Toast.LENGTH_LONG).show()
            }
        }

        connectBtn.setOnClickListener { connect() }
        scanBtn.setOnClickListener { startScan() }
    }

    private fun startScan() {
        val options = ScanOptions().apply {
            setDesiredBarcodeFormats(ScanOptions.QR_CODE)
            setPrompt("Point at the QR code on your laptop screen")
            setBeepEnabled(true)
            setOrientationLocked(false)
        }
        qrScanner.launch(options)
    }

    private fun connect() {
        var addr = serverInput.text.toString().trim()
        if (addr.isEmpty()) {
            Toast.makeText(this, "Enter the server address", Toast.LENGTH_SHORT).show()
            return
        }
        if (!addr.startsWith("http://") && !addr.startsWith("https://")) {
            addr = "http://$addr"
        }
        if (addr.endsWith("/")) addr = addr.dropLast(1)

        // save for next launch
        getSharedPreferences("rtc", Context.MODE_PRIVATE)
            .edit().putString("server", serverInput.text.toString().trim()).apply()

        connectPanel.visibility = View.GONE
        webView.visibility = View.VISIBLE
        webView.loadUrl(addr)
    }

    private fun disconnect() {
        webView.stopLoading()
        webView.loadUrl("about:blank")
        webView.visibility = View.GONE
        connectPanel.visibility = View.VISIBLE
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (webView.visibility == View.VISIBLE) {
            val now = System.currentTimeMillis()
            if (now - lastBackPress < 2000) {
                disconnect()
            } else {
                lastBackPress = now
                Toast.makeText(this, "Press back again to disconnect",
                    Toast.LENGTH_SHORT).show()
            }
        } else {
            super.onBackPressed()
        }
    }

    override fun onPause() {
        super.onPause()
        // pause the stream so the session is dropped cleanly while
        // the app is in the background...
        webView.evaluateJavascript(
            "window.pauseSession && window.pauseSession();", null)
        webView.onPause()
    }

    override fun onResume() {
        super.onResume()
        // ...and reconnect automatically when we come back
        webView.onResume()
        webView.evaluateJavascript(
            "window.resumeSession && window.resumeSession();", null)
    }

    override fun onDestroy() {
        webView.destroy()
        super.onDestroy()
    }
}
