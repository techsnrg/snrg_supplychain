frappe.provide("snrg_supplychain.packed_carton_touch");

frappe.pages["packed_carton_touch"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Packed Carton Touch"),
		single_column: true,
	});

	snrg_supplychain.packed_carton_touch.init(wrapper, page);
};

snrg_supplychain.packed_carton_touch.init = function (wrapper, page) {
	const controller = new snrg_supplychain.packed_carton_touch.Controller(wrapper, page);
	$(wrapper).data("controller", controller);
};

snrg_supplychain.packed_carton_touch.Controller = class PackedCartonTouchController {
	constructor(wrapper, page) {
		this.wrapper = $(wrapper);
		this.page = page;
		this.state = {
			doc: null,
			items: [],
			totals: {
				lines: 0,
				pieces: 0,
				net_weight_kg: 0,
				gross_weight_kg: 0,
			},
		};

		this.renderShell();
		this.bindPageActions();
		this.loadDoc();
	}

	get routeName() {
		return frappe.get_route()[1] || frappe.route_options?.name || "";
	}

	renderShell() {
		this.wrapper.find(".layout-main-section").html(`
			<div class="pct-touch">
				<div class="pct-hero">
					<div>
						<div class="pct-kicker">${__("Touch Mode")}</div>
						<h1 class="pct-title">${__("Packed Carton")}</h1>
						<div class="pct-subtitle">${__("Fast, touch-friendly carton packing for phones and tablets")}</div>
					</div>
					<div class="pct-hero-actions">
						<button class="btn btn-default pct-open-form">${__("Open Standard Form")}</button>
					</div>
				</div>

				<div class="pct-grid">
					<section class="pct-card pct-card--form">
						<div class="pct-card-title">${__("Carton Details")}</div>
						<div class="pct-fields">
							<div class="pct-field" data-field="name"></div>
							<div class="pct-field" data-field="box_type"></div>
							<div class="pct-field" data-field="packed_date"></div>
							<div class="pct-field" data-field="warehouse"></div>
							<div class="pct-field" data-field="packed_by"></div>
							<div class="pct-field" data-field="status"></div>
						</div>
					</section>

					<section class="pct-card pct-card--summary">
						<div class="pct-card-title">${__("Summary")}</div>
						<div class="pct-summary-grid">
							<div class="pct-summary-box">
								<div class="pct-summary-label">${__("Lines")}</div>
								<div class="pct-summary-value" data-total="lines">0</div>
							</div>
							<div class="pct-summary-box">
								<div class="pct-summary-label">${__("Total Qty")}</div>
								<div class="pct-summary-value" data-total="pieces">0</div>
							</div>
							<div class="pct-summary-box">
								<div class="pct-summary-label">${__("Net Weight")}</div>
								<div class="pct-summary-value" data-total="net_weight_kg">0.000 kg</div>
							</div>
							<div class="pct-summary-box">
								<div class="pct-summary-label">${__("Gross Weight")}</div>
								<div class="pct-summary-value" data-total="gross_weight_kg">0.000 kg</div>
							</div>
						</div>
						<div class="pct-summary-meta">
							<div><strong>${__("Dimensions")}:</strong> <span data-meta="dimensions">-</span></div>
							<div><strong>${__("Empty Box")}:</strong> <span data-meta="empty_weight_g">0 g</span></div>
						</div>
					</section>
				</div>

				<section class="pct-card pct-card--actions">
					<div class="pct-card-title">${__("Actions")}</div>
					<div class="pct-action-row">
						<button class="btn btn-primary btn-lg pct-add-item">${__("+ Add Item")}</button>
						<button class="btn btn-default btn-lg pct-clear-items">${__("Clear Items")}</button>
						<button class="btn btn-default btn-lg pct-print">${__("Print Sticker")}</button>
					</div>
				</section>

				<section class="pct-card pct-card--items">
					<div class="pct-card-title">${__("Items In Carton")}</div>
					<div class="pct-items-list"></div>
					<div class="pct-empty-state">${__("No items added yet. Tap '+ Add Item' to begin.")}</div>
				</section>

				<div class="pct-footer-actions">
					<button class="btn btn-default btn-lg pct-save-draft">${__("Save Draft")}</button>
					<button class="btn btn-primary btn-lg pct-save-print">${__("Save & Print")}</button>
				</div>
			</div>
		`);

		if (!document.getElementById("pct-touch-style")) {
			$("head").append(`
				<style id="pct-touch-style">
					.pct-touch { padding: 16px; background: linear-gradient(180deg, #fff6de 0%, #fffdf7 100%); min-height: calc(100vh - 120px); }
					.pct-hero { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:16px; }
					.pct-kicker { text-transform:uppercase; letter-spacing:.12em; font-size:12px; color:#8b5e00; font-weight:700; }
					.pct-title { margin:4px 0; font-size:40px; line-height:1; font-weight:900; color:#2e2416; }
					.pct-subtitle { font-size:16px; color:#6f5b3e; max-width:560px; }
					.pct-grid { display:grid; grid-template-columns:1.5fr 1fr; gap:16px; margin-bottom:16px; }
					.pct-card { background:#fff; border:1px solid #f0dcc0; border-radius:24px; padding:18px; box-shadow:0 10px 30px rgba(99,64,10,.08); }
					.pct-card-title { font-size:14px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; color:#7a5b20; margin-bottom:14px; }
					.pct-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
					.pct-field .control-label { font-size:13px; font-weight:700; color:#61471f; margin-bottom:8px; }
					.pct-field .control-input-wrapper input,
					.pct-field .control-input-wrapper .control-value,
					.pct-field .control-input-wrapper .awesomplete input,
					.pct-field .control-input-wrapper select {
						min-height:58px; border-radius:18px; font-size:24px; font-weight:700; background:#fffdf7;
					}
					.pct-summary-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
					.pct-summary-box { background:#fff8ea; border:1px solid #f2dfbe; border-radius:20px; padding:16px; }
					.pct-summary-label { font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:#876939; font-weight:700; margin-bottom:6px; }
					.pct-summary-value { font-size:30px; font-weight:900; color:#2d2418; }
					.pct-summary-meta { margin-top:14px; font-size:16px; color:#5f4a2d; display:grid; gap:6px; }
					.pct-action-row, .pct-footer-actions { display:flex; flex-wrap:wrap; gap:12px; }
					.pct-action-row .btn, .pct-footer-actions .btn, .pct-open-form { min-height:58px; border-radius:18px; font-size:22px; font-weight:800; padding:0 22px; }
					.pct-items-list { display:grid; gap:14px; }
					.pct-item-card { border:1px solid #f0dfc2; border-radius:22px; padding:16px; background:#fffdf9; }
					.pct-item-code { font-size:28px; font-weight:900; color:#2d2418; }
					.pct-item-name { font-size:20px; color:#54422a; margin-top:4px; }
					.pct-item-meta { display:flex; flex-wrap:wrap; gap:14px; margin-top:10px; color:#7a6138; font-size:16px; font-weight:700; }
					.pct-item-actions { display:flex; flex-wrap:wrap; justify-content:space-between; gap:12px; align-items:center; margin-top:14px; }
					.pct-qty-controls { display:flex; gap:10px; align-items:center; }
					.pct-qty-btn { min-width:56px; min-height:56px; border:none; border-radius:16px; background:#1f6feb; color:#fff; font-size:30px; font-weight:900; }
					.pct-qty-display { min-width:86px; text-align:center; font-size:30px; font-weight:900; color:#2e2416; background:#fff; border:1px solid #eddab8; border-radius:16px; padding:10px 14px; }
					.pct-remove-item { min-height:52px; border-radius:14px; font-size:18px; font-weight:800; }
					.pct-empty-state { display:none; padding:26px; border:2px dashed #e3cfa9; border-radius:22px; text-align:center; font-size:20px; font-weight:700; color:#8a6f45; background:#fffaf0; }
					.pct-empty-state.is-visible { display:block; }
					@media (max-width: 900px) {
						.pct-touch { padding:12px; }
						.pct-hero, .pct-grid, .pct-fields { grid-template-columns:1fr; display:grid; }
						.pct-title { font-size:32px; }
						.pct-fields { grid-template-columns:1fr; }
						.pct-summary-grid { grid-template-columns:1fr 1fr; }
						.pct-card { border-radius:20px; padding:14px; }
						.pct-action-row .btn, .pct-footer-actions .btn { flex:1 1 100%; }
						.pct-item-code { font-size:24px; }
						.pct-item-name { font-size:18px; }
					}
				</style>
			`);
		}

		this.$itemsList = this.wrapper.find(".pct-items-list");
		this.$emptyState = this.wrapper.find(".pct-empty-state");
	}

	bindPageActions() {
		this.wrapper.on("click", ".pct-open-form", () => this.openStandardForm());
		this.wrapper.on("click", ".pct-add-item", () => this.openAddItemDialog());
		this.wrapper.on("click", ".pct-clear-items", () => this.clearItems());
		this.wrapper.on("click", ".pct-save-draft", () => this.saveDoc());
		this.wrapper.on("click", ".pct-save-print", async () => {
			await this.saveDoc();
			this.printDoc();
		});
		this.wrapper.on("click", ".pct-print", () => this.printDoc());
		this.wrapper.on("click", ".pct-qty-btn", (e) => this.adjustQty(e));
		this.wrapper.on("click", ".pct-remove-item", (e) => this.removeItem(e));
	}

	async loadDoc() {
		const docname = this.routeName;
		const response = await frappe.call({
			method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.get_touch_carton",
			args: { name: docname || null },
			freeze: true,
			freeze_message: __("Loading carton..."),
		});

		this.state.doc = response.message;
		this.state.items = (response.message.items || []).map((item) => ({ ...item }));
		this.renderControls();
		this.render();
	}

	renderControls() {
		const doc = this.state.doc;
		const fields = [
			{ fieldname: "name", label: __("Carton ID"), fieldtype: "Data", read_only: 1 },
			{ fieldname: "box_type", label: __("Box Type"), fieldtype: "Link", options: "Carton Type", reqd: 1 },
			{ fieldname: "packed_date", label: __("Packed Date"), fieldtype: "Date", reqd: 1 },
			{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse", reqd: 1 },
			{ fieldname: "packed_by", label: __("Packed By"), fieldtype: "Link", options: "Employee" },
			{ fieldname: "status", label: __("Status"), fieldtype: "Data", read_only: 1 },
		];

		this.controls = {};
		fields.forEach((df) => {
			const container = this.wrapper.find(`.pct-field[data-field="${df.fieldname}"]`);
			container.empty();
			const control = frappe.ui.form.make_control({
				parent: container,
				df: {
					...df,
					change: () => this.onFieldChange(df.fieldname),
				},
				render_input: true,
			});
			control.set_value(doc[df.fieldname] || "");
			if (df.read_only) {
				control.df.read_only = 1;
				control.refresh();
			}
			this.controls[df.fieldname] = control;
		});
	}

	onFieldChange(fieldname) {
		if (!this.state.doc) return;
		this.state.doc[fieldname] = this.controls[fieldname].get_value();

		if (fieldname === "box_type") {
			if (!this.state.doc.box_type) {
				this.state.doc.dimensions = "";
				this.state.doc.empty_weight_g = 0;
				this.renderSummary();
				return;
			}

			frappe.db.get_doc("Carton Type", this.state.doc.box_type).then((doc) => {
				this.state.doc.dimensions = `${doc.length_in} × ${doc.width_in} × ${doc.height_in} in`;
				this.state.doc.empty_weight_g = doc.empty_weight_g || 0;
				this.renderSummary();
			});
		}
	}

	computeTotals() {
		const net = this.state.items.reduce((sum, item) => sum + (flt(item.qty) * flt(item.item_weight_kg)), 0);
		const pieces = this.state.items.reduce((sum, item) => sum + flt(item.qty), 0);
		const emptyWeight = flt(this.state.doc.empty_weight_g || 0) / 1000;
		this.state.totals = {
			lines: this.state.items.length,
			pieces,
			net_weight_kg: parseFloat(net.toFixed(3)),
			gross_weight_kg: parseFloat((net + emptyWeight).toFixed(3)),
		};
		this.state.doc.net_weight_kg = this.state.totals.net_weight_kg;
		this.state.doc.gross_weight_kg = this.state.totals.gross_weight_kg;
	}

	render() {
		this.computeTotals();
		this.renderItems();
		this.renderSummary();
	}

	renderSummary() {
		this.computeTotals();
		const totals = this.state.totals;
		this.wrapper.find('[data-total="lines"]').text(totals.lines);
		this.wrapper.find('[data-total="pieces"]').text(totals.pieces);
		this.wrapper.find('[data-total="net_weight_kg"]').text(`${totals.net_weight_kg.toFixed(3)} kg`);
		this.wrapper.find('[data-total="gross_weight_kg"]').text(`${totals.gross_weight_kg.toFixed(3)} kg`);
		this.wrapper.find('[data-meta="dimensions"]').text(this.state.doc.dimensions || "-");
		this.wrapper.find('[data-meta="empty_weight_g"]').text(`${flt(this.state.doc.empty_weight_g || 0).toFixed(0)} g`);
		this.controls.name?.set_value(this.state.doc.name || __("New Carton"));
		this.controls.status?.set_value(this.state.doc.status || __("Available"));
	}

	renderItems() {
		if (!this.state.items.length) {
			this.$itemsList.empty();
			this.$emptyState.addClass("is-visible");
			return;
		}

		this.$emptyState.removeClass("is-visible");
		this.$itemsList.html(
			this.state.items
				.map((item, index) => `
					<div class="pct-item-card" data-index="${index}">
						<div class="pct-item-code">${frappe.utils.escape_html(item.item_code)}</div>
						<div class="pct-item-name">${frappe.utils.escape_html(item.item_name || "")}</div>
						<div class="pct-item-meta">
							<span>${__("UOM")}: ${frappe.utils.escape_html(item.uom || "")}</span>
							<span>${__("Weight")}: ${flt(item.item_weight_kg).toFixed(3)} kg/${__("unit")}</span>
						</div>
						<div class="pct-item-actions">
							<div class="pct-qty-controls">
								<button class="pct-qty-btn" data-direction="-1" data-index="${index}">-</button>
								<div class="pct-qty-display">${flt(item.qty)}</div>
								<button class="pct-qty-btn" data-direction="1" data-index="${index}">+</button>
							</div>
							<button class="btn btn-danger pct-remove-item" data-index="${index}">${__("Remove Item")}</button>
						</div>
					</div>
				`)
				.join("")
		);
	}

	async openAddItemDialog() {
		const d = new frappe.ui.Dialog({
			title: __("Add Item"),
			fields: [
				{
					fieldname: "item_code",
					fieldtype: "Link",
					options: "Item",
					label: __("Item"),
					reqd: 1,
				},
				{
					fieldname: "qty",
					fieldtype: "Float",
					label: __("Qty"),
					reqd: 1,
					default: 1,
				},
			],
			primary_action_label: __("Add"),
			primary_action: async (values) => {
				if (!values.item_code || !(values.qty > 0)) {
					frappe.show_alert({ indicator: "orange", message: __("Please choose an item and enter a valid quantity.") });
					return;
				}

				const response = await frappe.call({
					method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.get_touch_item",
					args: { item_code: values.item_code },
				});
				const item = response.message;
				const existing = this.state.items.find((row) => row.item_code === item.item_code);
				if (existing) {
					existing.qty = flt(existing.qty) + flt(values.qty);
				} else {
					this.state.items.push({
						item_code: item.item_code,
						item_name: item.item_name,
						uom: item.uom,
						item_weight_kg: item.item_weight_kg,
						qty: flt(values.qty),
					});
				}

				this.render();
				d.hide();
			},
		});
		d.show();
	}

	adjustQty(event) {
		const $btn = $(event.currentTarget);
		const index = cint($btn.data("index"));
		const direction = cint($btn.data("direction"));
		const item = this.state.items[index];
		if (!item) return;

		item.qty = Math.max(1, flt(item.qty) + direction);
		this.render();
	}

	removeItem(event) {
		const index = cint($(event.currentTarget).data("index"));
		this.state.items.splice(index, 1);
		this.render();
	}

	clearItems() {
		if (!this.state.items.length) return;
		this.state.items = [];
		this.render();
	}

	buildPayload() {
		return {
			name: this.state.doc.name || null,
			box_type: this.controls.box_type.get_value(),
			packed_date: this.controls.packed_date.get_value(),
			warehouse: this.controls.warehouse.get_value(),
			packed_by: this.controls.packed_by.get_value(),
			items: this.state.items,
		};
	}

	async saveDoc() {
		const response = await frappe.call({
			method: "snrg_supplychain.supply_chain.doctype.packed_carton.packed_carton.save_touch_carton",
			args: { payload: JSON.stringify(this.buildPayload()) },
			freeze: true,
			freeze_message: __("Saving carton..."),
		});

		this.state.doc = response.message;
		this.state.items = (response.message.items || []).map((item) => ({ ...item }));
		if (this.state.doc.name && this.routeName !== this.state.doc.name) {
			frappe.set_route("packed_carton_touch", this.state.doc.name);
		}
		frappe.show_alert({ indicator: "green", message: __(`${this.state.doc.name} saved`) });
		this.renderControls();
		this.render();
		return this.state.doc;
	}

	openStandardForm() {
		if (this.state.doc?.name) {
			frappe.set_route("Form", "Packed Carton", this.state.doc.name);
			return;
		}
		frappe.new_doc("Packed Carton");
	}

	printDoc() {
		if (!this.state.doc?.name) {
			frappe.show_alert({ indicator: "orange", message: __("Save the carton before printing.") });
			return;
		}
		const url = `/printview?doctype=Packed%20Carton&name=${encodeURIComponent(this.state.doc.name)}&format=Carton%20Sticker&no_letterhead=1&_lang=en`;
		window.open(url, "_blank");
	}
};
