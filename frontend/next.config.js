/** @type {import('next').NextConfig} */

// The Docker deployment needs a server (output: "standalone") so nginx can
// proxy /api/* to the backend container. The desktop build (Electron) needs
// a plain static folder instead — Electron loads index.html straight off
// disk and talks to the local engine via window.hcd.engineUrl(), so rewrites
// (which require a running Next.js server) don't apply and aren't supported
// alongside static export anyway.
//
// The GitHub Actions desktop build sets DESKTOP_BUILD=1 before `npm run
// build` to switch into static-export mode; the normal Docker build leaves
// it unset and gets the original standalone+rewrites behavior.
const isDesktopBuild = process.env.DESKTOP_BUILD === "1";

const nextConfig = isDesktopBuild
  ? {
      output: "export",
      images: { unoptimized: true },
    }
  : {
      output: "standalone",
      async rewrites() {
        return [
          {
            source: "/api/:path*",
            destination: `${process.env.NEXT_PUBLIC_API_URL || "http://backend:8000"}/api/:path*`,
          },
        ];
      },
    };

module.exports = nextConfig;
