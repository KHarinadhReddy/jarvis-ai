# Keep serialization metadata for our @Serializable API models.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keepclasseswithmembers class kotlinx.serialization.json.** { kotlinx.serialization.KSerializer serializer(...); }
-keep,includedescriptorclasses class ai.jarvis.mobile.**$$serializer { *; }
-keepclassmembers class ai.jarvis.mobile.** { *** Companion; }
-keepclasseswithmembers class ai.jarvis.mobile.** { kotlinx.serialization.KSerializer serializer(...); }
