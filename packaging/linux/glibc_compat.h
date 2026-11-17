/* Force-included (-include) when Tk is rebuilt with Xft for the AppImage (packaging/build_tk_xft.sh).
 * A library linked on a recent distribution binds to the newest version of each glibc symbol, and would then refuse
 * to load on any older glibc. Tk only needs the long-standing behaviour of these functions, so they are bound to the
 * base x86_64 version: the result loads on old glibc, like the standalone Python it is bundled with.
 * (The C23 strtol/sscanf variants are avoided with -std=gnu11.) */
#if defined(__x86_64__) && defined(__linux__)
#define MXL_OLD(sym) __asm__(".symver " #sym "," #sym "@GLIBC_2.2.5")
MXL_OLD(pow);   MXL_OLD(powf);   MXL_OLD(exp);  MXL_OLD(expf);  MXL_OLD(log);   MXL_OLD(logf);  MXL_OLD(log2);
MXL_OLD(hypot); MXL_OLD(hypotf); MXL_OLD(fmod); MXL_OLD(fmodf); MXL_OLD(acosf); MXL_OLD(asinf); MXL_OLD(atan2f);
MXL_OLD(sqrtf); MXL_OLD(exp2);   MXL_OLD(memcpy);
#endif
