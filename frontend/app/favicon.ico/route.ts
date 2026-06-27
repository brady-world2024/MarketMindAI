export function GET() {
  return new Response("", {
    status: 200,
    headers: {
      "Content-Type": "image/x-icon",
      "Cache-Control": "public, max-age=86400",
    },
  });
}
