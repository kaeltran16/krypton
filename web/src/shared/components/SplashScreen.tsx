export function SplashScreen() {
  return (
    <div className="fixed inset-0 z-[9999] bg-[#080c12]">
      <img
        src="/splash.webp"
        alt=""
        className="absolute inset-0 w-full h-full object-cover"
      />
    </div>
  );
}
