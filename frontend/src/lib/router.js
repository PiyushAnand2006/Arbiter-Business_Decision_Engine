import { useEffect, useState } from "react";

// Tiny hash router: #/review/14 -> { page: "review", id: "14" }. Deep links + back button work.
const parse = () => {
  const [page = "overview", id = null] = window.location.hash.replace(/^#\/?/, "").split("/");
  return { page: page || "overview", id: id ? decodeURIComponent(id) : null };
};

export function useRoute() {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function navigate(page, id) {
  const next = `#/${page}${id != null ? `/${encodeURIComponent(id)}` : ""}`;
  if (window.location.hash !== next) window.location.hash = next;
}
