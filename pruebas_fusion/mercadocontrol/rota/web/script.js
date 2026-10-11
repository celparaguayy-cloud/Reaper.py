const lista = document.getElementById("lista");
const error = document.getElementById("error");

async function cargar() {
  const r = await fetch("/api/productos");
  const productos = await r.json();
  lista.replaceChildren(...productos.map((p) => {
    const fila = document.createElement("tr");
    for (const valor of [p.nombre, p.precio, p.stock]) {
      const celda = document.createElement("td");
      celda.textContent = String(valor);
      fila.appendChild(celda);
    }
    const borrar = document.createElement("button");
    borrar.textContent = "Eliminar";
    borrar.onclick = async () => { await fetch(`/api/productos/${p.id}`, { method: "DELETE" }); cargar(); };
    const celda = document.createElement("td");
    celda.appendChild(borrar);
    fila.appendChild(celda);
    return fila;
  }));
}

document.getElementById("alta").addEventListener("submit", async (e) => {
  e.preventDefault();
  const datos = Object.fromEntries(new FormData(e.target));
  const r = await fetch("/api/productos", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nombre: datos.nombre, precio: Number(datos.precio), stock: Number(datos.stock) }),
  });
  error.textContent = r.ok ? "" : (await r.json()).error;
  if (r.ok) { e.target.reset(); cargar(); }
});

cargar();
